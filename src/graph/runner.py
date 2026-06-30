"""Run a single analysis through the ReAct graph.

Phase 3 signature: adds sessions (multi-turn), pre-flight (C26 clarification +
C19 selector), follow-up suggestions, and the C29 prompt_breakdown. Pre-flight
runs ONLY when the datasets are NOT explicit (`run_selector=True`) — explicit
`dataset_ids` (the Phase-2 direct path) skip BOTH clarification and the selector,
per `spec/agent.md` ("Pre-flight ... is SKIPPED when explicit dataset_ids are
supplied").

The runner creates the `query_runs` row, runs pre-flight, invokes the compiled
`agentic_ai` graph, persists the result, calls `generate_suggestions`, and
returns the `/ask` payload. It does NOT commit/push and is provider-agnostic
(all LLM calls go through `LLMClient`).
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
from graph.nodes import get_derived_created, release_derived_created
from graph.preflight import check_clarification, select_datasets
from graph.state import AgentState
from graph.suggestions import generate_suggestions
from observability.events import get_logger

logger = get_logger("graph.runner")


def _uploads_dir() -> Path:
    """`uploads/` at the repo root (two levels up from src/graph/)."""
    return Path(__file__).resolve().parent.parent.parent / "uploads"


def _candidate_schemas(dataset_ids: list[str]) -> tuple[list[dict], str]:
    """Build a compact schema view of each candidate dataset for pre-flight.

    Returns `(schemas, schemas_text)`:
    - `schemas`: list of `{"id", "filename", "columns", "notes"}` dicts for
      `select_datasets`.
    - `schemas_text`: a human-readable block for `check_clarification`.

    Columns come from the cheap `datasets.columns_json` metadata (no file read).
    Falls back to a header-only Parquet/CSV peek if the column list is missing.
    """
    schemas: list[dict] = []
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
            schemas.append(
                {"id": dataset_id, "filename": filename, "columns": columns, "notes": notes}
            )
            cols_text = ", ".join(str(c) for c in columns)
            block = f"- {filename} (id {dataset_id}): columns [{cols_text}]"
            if notes:
                block += f"; notes: {notes[:200]}"
            text_parts.append(block)

    return schemas, "\n".join(text_parts)


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


# The six C29 component keys (the frontend renders these). `total_prompt` is their
# exact sum — see spec/capabilities/context-window-display.md.
_BREAKDOWN_COMPONENT_KEYS = (
    "system_overhead",
    "dataset_schemas",
    "dataset_notes",
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
    added to the largest bucket so the six components sum EXACTLY to `tokens_input`.
    `total_prompt` is the real cumulative input; `tokens_output` is the real
    cumulative output (carried for the response). This aligns the breakdown with the
    "Last query (In / Out)" row. See spec/capabilities/context-window-display.md.

    Fallback (a run that never planned — clarification short-circuit,
    cancelled-before-plan, or zero total chars): the six buckets are 0,
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
    # Fix rounding so the six sum EXACTLY to real_in: push the residual into the
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
    run_selector: bool = False,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """Run a single analysis; return the `/ask` payload.

    Pre-flight (clarification + selector) runs ONLY when `run_selector=True`
    (datasets NOT explicit). With explicit ids (`run_selector=False`, the default
    Phase-2 path) BOTH pre-flight calls are skipped.

    Returns either:
    - a clarification short-circuit (no graph run):
      `{"type":"clarification","run_id","clarification_question","session_id"}`
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
    candidate_ids = [d for d in (dataset_ids or []) if d]
    conversation_history = conversation_history or []

    selector_reasoning: str | None = None
    resolved_ids = list(candidate_ids)

    # ------------------------------------------------------------------ #
    # Pre-flight (only when datasets are NOT explicit).
    # ------------------------------------------------------------------ #
    if run_selector:
        schemas, schemas_text = _candidate_schemas(candidate_ids)

        # 1. C26 clarification — short-circuit on an ambiguous question.
        if not skip_clarification:
            clarification = check_clarification(question, schemas_text)
            if clarification:
                with create_db_session() as session:
                    row = QueryRunRow(
                        dataset_id=candidate_ids[0] if candidate_ids else None,
                        session_id=session_id,
                        question=question,
                        status="clarification",
                        answer=clarification,
                        dataset_ids_json=list(candidate_ids),
                        iteration_count=0,
                        tokens_input=0,
                        tokens_output=0,
                    )
                    session.add(row)
                    session.flush()
                    clar_run_id = row.id
                logger.info("clarification_returned", run_id=clar_run_id, session_id=session_id)
                return {
                    "type": "clarification",
                    "run_id": clar_run_id,
                    "clarification_question": clarification,
                    "session_id": session_id,
                }

        # 2. C19 selector — pick the minimal dataset subset (fall back to all).
        resolved_ids, selector_reasoning = select_datasets(question, schemas, candidate_ids)

    # ------------------------------------------------------------------ #
    # Create the query_runs row (status=running) with the FINAL ids.
    # ------------------------------------------------------------------ #
    with create_db_session() as session:
        row = QueryRunRow(
            dataset_id=resolved_ids[0] if resolved_ids else None,
            session_id=session_id,
            question=question,
            status="running",
            dataset_ids_json=list(resolved_ids),
            selector_reasoning=selector_reasoning,
            iteration_count=0,
            tokens_input=0,
            tokens_output=0,
        )
        session.add(row)
        session.flush()
        run_id = row.id

    logger.info(
        "run_start",
        run_id=run_id,
        datasets=len(resolved_ids),
        max_iterations=cap,
        session_id=session_id,
        run_selector=run_selector,
    )

    # ------------------------------------------------------------------ #
    # Build the initial AgentState and invoke the graph.
    # ------------------------------------------------------------------ #
    initial: AgentState = {
        "run_id": run_id,
        "dataset_ids": list(resolved_ids),
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
        "selector_reasoning": selector_reasoning,
    }

    config = {"recursion_limit": cap * 3 + 10}
    final: dict[str, Any] = agentic_ai.invoke(initial, config=config)

    status = final.get("status", "completed")
    answer = final.get("answer")
    action_history = final.get("action_history") or []
    iteration_count = final.get("iteration_count", 0)
    tokens_input = final.get("tokens_input", 0)
    tokens_output = final.get("tokens_output", 0)
    error_message = final.get("error_message") or final.get("error")
    selector_reasoning = final.get("selector_reasoning", selector_reasoning)
    charts = final.get("charts") or []
    # Derived datasets the agent persisted via save_dataset this run (C25). Read
    # the run-scoped registry, then release it.
    derived_dataset_ids = get_derived_created(run_id)
    release_derived_created(run_id)
    is_best_effort = status == "completed" and error_message in (
        "max_iterations",
        "consecutive_errors",
    )

    # ------------------------------------------------------------------ #
    # Follow-up suggestions (graph-adjacent; add its tokens to the total).
    # ------------------------------------------------------------------ #
    # A user-stopped run skips suggestions — stopping must not trigger MORE LLM
    # calls (that's the whole point).
    suggested_questions: list[str] = []
    if status == "completed" and answer and error_message != "cancelled":
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
        "dataset_ids": list(resolved_ids),
        "is_best_effort": is_best_effort,
        "selector_reasoning": selector_reasoning,
        "suggested_questions": suggested_questions,
        "prompt_breakdown": prompt_breakdown,
    }
