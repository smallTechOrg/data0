"""Run a single analysis through the ReAct graph.

Datasets are AGENT-DRIVEN: the runner hands the agent a metadata-only catalog of
ALL the workspace's datasets (built in `setup`) and the agent picks + lazily loads
whichever it needs. There is no pre-selection roundtrip — the only remaining
pre-flight is the C26 clarification check, run on the first turn of a conversation
(`run_clarification=True`) and skipped on follow-ups.

The run's recorded `dataset_ids` is therefore the set the agent ACTUALLY loaded
(used-tracking via `get_loaded_ids`), not the full candidate list: this keeps
"Datasets used" accurate and scopes the C15 cascade-delete to real dependencies
(recording every dataset would cascade-delete every conversation whenever any one
dataset is removed).

The runner creates the `query_runs` row, runs the clarification check, invokes the
compiled `agentic_ai` graph, records the agent's dataset pick, persists the result,
calls `generate_suggestions`, and returns the `/ask` payload. It does NOT
commit/push and is provider-agnostic (all LLM calls go through `LLMClient`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from config.db_overrides import get_runtime_max_iterations
from config.settings import get_settings
from db.models import DatasetRow, QueryRunRow
from db.session import create_db_session
from graph.agent import agentic_ai
from graph.cancellation import discard as discard_cancel
from graph.nodes import (
    get_derived_created,
    get_loaded_ids,
    release_dataframe,
    release_derived_created,
    release_loaded_ids,
)
from graph.preflight import check_clarification
from graph.state import AgentState
from graph.suggestions import generate_suggestions
from observability.events import get_logger

logger = get_logger("graph.runner")

# C35 Fast Mode: the tightened per-request `max_iterations` cap. WINS OVER both
# `settings.max_iterations` and any DB `SettingRow` override for this request only
# — never persisted, never written back. See spec/capabilities/fast-mode.md.
_FAST_MODE_MAX_ITERATIONS = 5


def _uploads_dir() -> Path:
    """`uploads/` at the repo root (two levels up from src/graph/)."""
    return Path(__file__).resolve().parent.parent.parent / "uploads"


def _candidate_schemas_text(dataset_ids: list[str]) -> str:
    """Build a human-readable schema block of the candidate datasets.

    The only remaining pre-flight consumer is the C26 `check_clarification` call
    (dataset SELECTION is now the agent's job, so no machine-readable schema list is
    needed). Columns come from the cheap `datasets.columns_json` metadata (no file
    read); falls back to a header-only Parquet/CSV peek if the column list is missing.
    """
    text_parts: list[str] = []
    with create_db_session() as session:
        for dataset_id in dataset_ids:
            row = session.get(DatasetRow, dataset_id)
            if row is None:
                continue
            columns = list(row.columns_json or [])
            if not columns:
                columns = _peek_columns(dataset_id)
            filename = row.filename or f"{dataset_id}.csv"
            notes = (row.context or "").strip()
            cols_text = ", ".join(str(c) for c in columns)
            block = f"- {filename} (id {dataset_id}): columns [{cols_text}]"
            if notes:
                block += f"; notes: {notes[:200]}"
            text_parts.append(block)
    return "\n".join(text_parts)


def _peek_columns(dataset_id: str) -> list[str]:
    """Cheap column-name peek from the data file (header only). Empty on failure."""
    base = _uploads_dir()
    parquet_path = base / f"{dataset_id}.parquet"
    csv_path = base / f"{dataset_id}.csv"
    try:
        if parquet_path.exists():
            return list(pd.read_parquet(parquet_path, columns=None).columns)
        if csv_path.exists():
            return list(pd.read_csv(csv_path, nrows=0).columns)
    except Exception as exc:  # noqa: BLE001 — peek is best-effort
        logger.warning("schema_peek_failed", dataset_id=dataset_id, error=str(exc))
    return []


# The five C29 component keys (the frontend renders these). `total_prompt` is their
# exact sum — see spec/capabilities/context-window-display.md.
_BREAKDOWN_COMPONENT_KEYS = (
    "system_overhead",
    "dataset_schemas",
    "memory",
    "history",
    "action_history",
)


def _build_prompt_breakdown(
    *,
    prompt_component_chars: dict | None,
    tokens_input: int,
    tokens_output: int,
) -> dict[str, int]:
    """C29: the CUMULATIVE input composition of the whole query, scaled to the real
    provider-reported cumulative `tokens_input`.

    `plan_action` accumulates per-bucket CHAR counts across all ReAct iterations on
    the state (`prompt_component_chars`). Here we scale those cumulative char counts
    to the real cumulative `tokens_input`: each bucket gets
    `round(cum[bucket] / total_chars * tokens_input)`, then the rounding residual is
    added to the largest bucket so the five components sum EXACTLY to `tokens_input`.
    `total_prompt` is the real cumulative input; `tokens_output` is the real
    cumulative output (carried for the response). This aligns the breakdown with the
    "Last query (In / Out)" row. See spec/capabilities/context-window-display.md.

    Fallback (a run that never planned — clarification short-circuit,
    cancelled-before-plan, or zero total chars): the five buckets are 0,
    `total_prompt` is `tokens_input` (likely 0), `tokens_output` is `tokens_output`.
    Never crashes.
    """
    cum = prompt_component_chars or {}
    total_chars = sum(int(cum.get(key, 0)) for key in _BREAKDOWN_COMPONENT_KEYS)
    real_in = int(tokens_input or 0)

    if total_chars <= 0:
        components = {key: 0 for key in _BREAKDOWN_COMPONENT_KEYS}
        components["total_prompt"] = real_in
        components["tokens_output"] = int(tokens_output or 0)
        return components

    components = {
        key: round(int(cum.get(key, 0)) / total_chars * real_in)
        for key in _BREAKDOWN_COMPONENT_KEYS
    }
    # Fix rounding so the five sum EXACTLY to real_in: push the residual into the
    # largest bucket (the most stable place to absorb a +/-1 adjustment).
    residual = real_in - sum(components.values())
    if residual:
        largest = max(_BREAKDOWN_COMPONENT_KEYS, key=lambda k: components[k])
        components[largest] += residual

    components["total_prompt"] = real_in
    components["tokens_output"] = int(tokens_output or 0)
    return components


def run_agent(
    question: str,
    dataset_ids: list[str],
    *,
    session_id: str | None = None,
    conversation_history: list[dict] | None = None,
    skip_clarification: bool = False,
    run_clarification: bool = False,
    max_iterations: int | None = None,
    fast_mode: bool = False,
) -> dict[str, Any]:
    """Run a single analysis; return the `/ask` payload.

    `dataset_ids` is the FULL candidate set (every dataset in the workspace) — the
    agent picks and lazily loads whichever it needs from the catalog `setup` builds.
    The C26 clarification check runs ONLY when `run_clarification=True` (the first
    turn of a conversation) and can be suppressed with `skip_clarification`.

    `fast_mode` (C35, per-request only — never a settings/DB default for future
    requests): applies a tightened `max_iterations` cap of `5` that WINS OVER both
    `settings.max_iterations` and any DB `SettingRow` override; skips the C26
    `check_clarification` call entirely (proceeds straight to the ReAct loop,
    regardless of `run_clarification`/`skip_clarification`); skips the post-answer
    `generate_suggestions` call. The completed run's value IS persisted on
    `QueryRunRow.fast_mode` below, purely so `GET /sessions/{id}` can report it
    (badge survives reload) — that is historical record-keeping, not a behavioral
    default. See spec/capabilities/fast-mode.md.

    The `query_runs` row is created with an EMPTY `dataset_ids_json` and updated
    after the graph returns with the ids the agent actually loaded (`get_loaded_ids`)
    — that used set is what drives "Datasets used", the C15 cascade, and the report.

    Returns either:
    - a clarification short-circuit (no graph run):
      `{"type":"clarification","run_id","clarification_question",
        "suggested_questions","session_id"}` — `suggested_questions` (C37) is up
      to 3 refined candidates from the SAME pre-flight call, `[]` on fallback
    - an answer:
      `{"type":"answer", run_id, status, answer, iteration_count, tokens_input,
        tokens_output, action_history, charts, derived_dataset_ids, dataset_ids,
        is_best_effort, selector_reasoning, suggested_questions,
        prompt_breakdown, session_id}`
    """
    settings = get_settings()
    cap = max_iterations if max_iterations is not None else settings.max_iterations
    # Read DB overrides (user-configured via /settings API). The model override
    # is applied inside LLMClient (_make_provider); here we apply max-iterations.
    _db_max_iter = get_runtime_max_iterations()
    if _db_max_iter is not None:
        cap = _db_max_iter
    # C35 Fast Mode: the tightened cap WINS OVER the settings/DB-override value
    # just applied above — evaluated LAST so it always has the final word for this
    # one request. Never written back to settings/DB.
    if fast_mode:
        cap = _FAST_MODE_MAX_ITERATIONS
    candidate_ids = [d for d in (dataset_ids or []) if d]
    conversation_history = conversation_history or []

    # Dataset selection is agent-driven: the C19 selector roundtrip is gone, so the
    # reasoning field is always None (kept in the payload/DB for schema stability).
    selector_reasoning: str | None = None

    # ------------------------------------------------------------------ #
    # Pre-flight: C26 clarification only, first turn of a conversation.
    # Fast Mode skips this call ENTIRELY (zero clarification roundtrips), even on
    # a first turn where a normal run would ask.
    # ------------------------------------------------------------------ #
    if run_clarification and not skip_clarification and not fast_mode:
        schemas_text = _candidate_schemas_text(candidate_ids)
        clarification = check_clarification(question, schemas_text)
        if clarification:
            with create_db_session() as session:
                row = QueryRunRow(
                    # A clarification turn depends on NO specific dataset: an empty id
                    # set keeps a dataset deletion (C15 cascade) from wiping the whole
                    # conversation just because it once asked a clarifying question.
                    dataset_id=None,
                    session_id=session_id,
                    question=question,
                    status="clarification",
                    # Only the question is persisted — C37 candidates are live-only
                    # (no DB column; a resumed clarification turn shows no chips).
                    answer=clarification.question,
                    dataset_ids_json=[],
                    iteration_count=0,
                    tokens_input=0,
                    tokens_output=0,
                )
                session.add(row)
                session.flush()
                clar_run_id = row.id
            logger.info(
                "clarification_returned",
                run_id=clar_run_id,
                session_id=session_id,
                suggestions=len(clarification.suggestions),
            )
            return {
                "type": "clarification",
                "run_id": clar_run_id,
                "clarification_question": clarification.question,
                # C37: up to 3 refined candidate questions from the SAME single
                # pre-flight call ([] when the reply fell back to plain text).
                "suggested_questions": list(clarification.suggestions),
                "session_id": session_id,
            }

    # ------------------------------------------------------------------ #
    # Create the query_runs row (status=running). `dataset_ids_json` starts
    # EMPTY — it is set post-run to the datasets the agent actually loaded.
    # ------------------------------------------------------------------ #
    with create_db_session() as session:
        row = QueryRunRow(
            dataset_id=None,
            session_id=session_id,
            question=question,
            status="running",
            dataset_ids_json=[],
            selector_reasoning=None,
            iteration_count=0,
            tokens_input=0,
            tokens_output=0,
            fast_mode=fast_mode,
        )
        session.add(row)
        session.flush()
        run_id = row.id

    logger.info(
        "run_start",
        run_id=run_id,
        candidates=len(candidate_ids),
        max_iterations=cap,
        session_id=session_id,
        run_clarification=run_clarification,
        fast_mode=fast_mode,
    )

    # ------------------------------------------------------------------ #
    # Build the initial AgentState and invoke the graph. The state carries the
    # FULL candidate set as `dataset_ids` — `setup` turns it into the catalog the
    # agent picks from; the agent's actual pick is read back after invoke.
    # ------------------------------------------------------------------ #
    initial: AgentState = {
        "run_id": run_id,
        "dataset_ids": list(candidate_ids),
        "session_id": session_id,
        "question": question,
        "conversation_history": conversation_history,
        "action_history": [],
        "iteration_count": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "charts": [],
        "status": "running",
        "max_iterations": cap,
        "error": None,
        "selector_reasoning": None,
        "fast_mode": fast_mode,
    }

    config = {"recursion_limit": cap * 3 + 10}
    try:
        final: dict[str, Any] = agentic_ai.invoke(initial, config=config)

        # Success-path registry READS — inside the `try`, before the `finally`
        # releases the registries.
        # The datasets the agent ACTUALLY loaded this run (used-tracking) — the
        # run's real dataset set (accurate "Datasets used" + correct C15 cascade
        # scope).
        used_ids = get_loaded_ids(run_id)
        # Derived datasets the agent persisted via save_dataset this run (C25).
        derived_dataset_ids = get_derived_created(run_id)
    finally:
        # Exception-safe release (Phase 11): the three terminal nodes are NOT the
        # only release path — an uncaught exception escaping any node used to leak
        # this run's registries (including the persisted eval namespace) for the
        # process lifetime. All three helpers are idempotent (`pop(run_id, None)`),
        # so the double release on the success path is harmless. An exception is
        # NOT swallowed here — it still propagates to the caller unchanged.
        release_dataframe(run_id)
        release_loaded_ids(run_id)
        release_derived_created(run_id)

    status = final.get("status", "completed")
    answer = final.get("answer")
    action_history = final.get("action_history") or []
    iteration_count = final.get("iteration_count", 0)
    tokens_input = final.get("tokens_input", 0)
    tokens_output = final.get("tokens_output", 0)
    error_message = final.get("error_message") or final.get("error")
    selector_reasoning = None  # agent-driven selection: no selector reasoning
    charts = final.get("charts") or []
    is_best_effort = status == "completed" and error_message in (
        "max_iterations",
        "consecutive_errors",
    )

    # ------------------------------------------------------------------ #
    # Follow-up suggestions (graph-adjacent; add its tokens to the total).
    # ------------------------------------------------------------------ #
    # A user-stopped run skips suggestions — stopping must not trigger MORE LLM
    # calls (that's the whole point). Fast Mode also skips this call entirely —
    # `suggested_questions` stays `[]`, same shape as any other empty-suggestions run.
    suggested_questions: list[str] = []
    if status == "completed" and answer and error_message != "cancelled" and not fast_mode:
        suggested_questions, s_in, s_out = generate_suggestions(question, answer)
        tokens_input += s_in
        tokens_output += s_out

    # C29 prompt breakdown: the CUMULATIVE input composition of the whole query,
    # scaled to the real cumulative tokens_input so it aligns with "Last query In".
    # Carries tokens_output (the real cumulative output) for the response.
    prompt_breakdown = _build_prompt_breakdown(
        prompt_component_chars=final.get("prompt_component_chars"),
        tokens_input=tokens_input,
        tokens_output=tokens_output,
    )

    # ------------------------------------------------------------------ #
    # Persist the result to the query_runs row.
    # ------------------------------------------------------------------ #
    with create_db_session() as session:
        row = session.get(QueryRunRow, run_id)
        if row is not None:
            row.status = status
            row.answer = answer
            row.action_history = action_history
            row.iteration_count = iteration_count
            row.tokens_input = tokens_input
            row.tokens_output = tokens_output
            row.error_message = error_message
            row.selector_reasoning = selector_reasoning
            row.prompt_breakdown = prompt_breakdown
            row.charts_json = charts or []
            # Record the agent's dataset pick (used-tracking): the run now "depends
            # on" exactly the datasets it loaded — nothing when it loaded none.
            row.dataset_id = used_ids[0] if used_ids else None
            row.dataset_ids_json = list(used_ids)

    # Clear any Stop flag now the run has ended (success, error, or cancelled).
    discard_cancel(run_id)

    logger.info(
        "run_done",
        run_id=run_id,
        status=status,
        iterations=iteration_count,
        is_best_effort=is_best_effort,
        suggestions=len(suggested_questions),
    )

    return {
        "type": "answer",
        "run_id": run_id,
        "session_id": session_id,
        "status": status,
        "answer": answer,
        "iteration_count": iteration_count,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "action_history": action_history,
        "charts": charts,
        "derived_dataset_ids": derived_dataset_ids,
        "dataset_ids": list(used_ids),
        "is_best_effort": is_best_effort,
        "selector_reasoning": selector_reasoning,
        "suggested_questions": suggested_questions,
        "prompt_breakdown": prompt_breakdown,
    }
