"""ReAct loop nodes (LangGraph).

Replaces the skeleton's `transform_text` graph. The six nodes implement the
Reason+Act loop from `spec/agent.md` -> "## Nodes / Steps":

    setup -> plan_action -> execute_action -> (loop) -> finalize / force_finalize
                                            -> handle_error (fatal)

All LLM calls go through `LLMClient` (never a provider SDK directly). The DataFrames
for a run live in the module-level `_dataframes` registry, keyed by `run_id`
(Phase 2 is the simple per-run load — no session cache; that lands in Phase 3).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from db.models import DatasetRow, QueryRunRow
from db.session import create_db_session
from graph.cancellation import is_cancelled  # cooperative Stop
from graph.memory import get_memory_block  # owned by slice-3c; 3b only imports it
from graph.sandbox import (
    _safe_alias,
    build_lazy_namespace,
    eval_expression,
    make_echart,
    make_save_dataset,
)
from graph.state import AgentState
from llm.client import LLMClient
from observability.events import get_logger

logger = get_logger("graph.nodes")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_PLAN_PROMPT_PATH = _PROMPTS_DIR / "plan_action.md"
_FINALIZE_PROMPT_PATH = _PROMPTS_DIR / "finalize.md"

# Run-scoped registry, keyed by `run_id`:
#   {run_id: {"session_id", "catalog": [{id,filename,alias,columns,notes}, ...],
#             "frames": {dataset_id: df}, "derived_frames": {alias: df}}}
# `setup` builds the metadata-only catalog of ALL candidate datasets; `frames` is
# filled LAZILY as the agent references datasets (see execute_action's loader), so
# a question never loads a table it doesn't touch. Released on finalize/error.
_dataframes: dict[str, dict[str, Any]] = {}

# Run-scoped registry of derived dataset ids created by `save_dataset` during a
# run (C25), keyed by `run_id` — mirrors `_dataframes`. The runner reads this via
# `get_derived_created(run_id)` to surface `derived_dataset_ids` in the payload,
# and it is cleared when the run's DataFrames are released.
_derived_created: dict[str, list[str]] = {}

# Run-scoped registry of the EXISTING dataset ids the agent actually LOADED during
# a run, keyed by `run_id` — the used-tracking that agent-driven selection needs.
# Kept SEPARATE from `_dataframes` (like `_derived_created`) so it survives the
# finalize node's `_release_dataframe`; the runner reads it via `get_loaded_ids`
# AFTER the graph returns, records it as the run's real `dataset_ids` (what the
# agent picked), then releases it. Doubles as save_dataset's parent lineage.
_loaded_ids: dict[str, list[str]] = {}

# Session DataFrame cache (C27): {session_id: {"frames": {dataset_id: df},
#   "order": [dataset_id, ...]}}. Reused across turns of the same conversation so
# a multi-turn session does not re-read Parquet/CSV every turn. Small LRU bound
# on the number of cached sessions (insertion order = LRU order; touch on hit).
_session_cache: dict[str, dict[str, Any]] = {}
_SESSION_CACHE_MAX = 8

# Node tags injected so the stub provider can branch deterministically.
_PLAN_TAG = "<node:plan>"
_FINALIZE_TAG = "<node:finalize>"

# How many consecutive execution errors force a wrap-up.
_MAX_CONSECUTIVE_ERRORS = 3

# C35 Fast Mode: truncate a step's stored `result` to this many characters (plus
# `_FAST_MODE_TRUNCATION_MARKER`) before it re-enters `action_history`. This is the
# STORED/re-transmitted value only — truncation happens ONCE at append time, so it
# compounds correctly across iterations (each later prompt re-sends the already-
# shortened result). See spec/capabilities/fast-mode.md.
_FAST_MODE_RESULT_MAX_CHARS = 500
_FAST_MODE_TRUNCATION_MARKER = "… [truncated]"

# C35 Fast Mode: one extra instruction line appended to the plan_action system
# prompt asking for a shorter final answer. Prompt-level guidance ONLY — never a
# hard max_output_tokens/max_tokens cap (risks mid-sentence truncation).
_FAST_MODE_BREVITY_LINE = (
    "\n\nFast Mode is ON: keep your `FINAL ANSWER:` brief — a few sentences unless "
    "the question genuinely needs a table or list."
)


def _truncate_result(text: str) -> str:
    """Truncate a step's result to `_FAST_MODE_RESULT_MAX_CHARS` (+ marker) when
    it exceeds that length. A short result is returned unchanged."""
    text = text or ""
    if len(text) <= _FAST_MODE_RESULT_MAX_CHARS:
        return text
    return text[:_FAST_MODE_RESULT_MAX_CHARS] + _FAST_MODE_TRUNCATION_MARKER


# Explicit visualization request: a conservative, case-insensitive match for words
# that unambiguously ask for a chart. Kept narrow on purpose — only explicit asks
# trip the deterministic chart guardrail (see `_wants_chart`).
_WANTS_CHART_RE = re.compile(
    r"\b(charts?|plots?|graphs?|visuali\w*|diagram|barchart|histogram)\b",
    re.IGNORECASE,
)
# Phrase-level asks that the word list above does not already cover.
_WANTS_CHART_PHRASE_RE = re.compile(r"with charts?|show me", re.IGNORECASE)


def _wants_chart(question: str) -> bool:
    """True when the question EXPLICITLY asks for a chart/visualization.

    Conservative by design: matches only explicit visualization vocabulary
    ("chart", "plot", "graph", "visuali…", "diagram", "histogram", "barchart") or
    the phrases "with charts" / "show me". A plain analytical question ("what is
    the average price?") returns False so the guardrail never fires spuriously.
    """
    q = question or ""
    return bool(_WANTS_CHART_RE.search(q) or _WANTS_CHART_PHRASE_RE.search(q))


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _estimate_tokens(text: str) -> int:
    """Rough token estimate when the provider does not report usage.

    ~4 chars/token is the documented heuristic (see spec/agent.md plan_action).
    """
    return max(1, len(text or "") // 4)


def _uploads_dir() -> Path:
    """`uploads/` at the repo root (two levels up from src/graph/)."""
    return Path(__file__).resolve().parent.parent.parent / "uploads"


def _load_dataframe(dataset_id: str) -> pd.DataFrame:
    """Load a dataset's DataFrame: Parquet preferred, CSV fallback.

    Raises on a missing/unreadable file (fatal -> handle_error).
    """
    base = _uploads_dir()
    parquet_path = base / f"{dataset_id}.parquet"
    csv_path = base / f"{dataset_id}.csv"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    raise FileNotFoundError(
        f"No data file for dataset {dataset_id!r} (looked for {parquet_path.name} / {csv_path.name})"
    )


def _facts_as_notes(facts: list[str]) -> str:
    """Render C31 compressed facts as a compact notes string for the prompt.

    C31: the catalog's dataset notes are ALWAYS the pre-compressed `context_facts`
    (rendered here) — the raw, uncompressed notes are never sent to the LLM. `setup`
    reads only cached facts and does NOT compress on demand (the catalog spans every
    dataset, so a synchronous compress-per-dataset would be a first-turn storm); a
    dataset with no facts cached yet simply shows columns only.
    """
    return "; ".join(f.strip() for f in facts if f and str(f).strip())


def _safe_memory_block() -> str:
    """Read the global persistent memory block (slice-3c), defensively.

    A 3c regression (import/runtime failure) must NEVER crash planning, so any
    exception yields an empty block — planning simply proceeds without memory.
    """
    try:
        return (get_memory_block() or "").strip()
    except Exception as exc:  # noqa: BLE001 — memory is best-effort context
        logger.warning("memory_block_failed", error=str(exc))
        return ""


# --------------------------------------------------------------------------- #
# Session DataFrame cache (C27)
# --------------------------------------------------------------------------- #


def _session_load_frame(session_id: str, dataset_id: str) -> pd.DataFrame:
    """Return the DataFrame for `dataset_id` within `session_id`, using the cache.

    On a cache HIT: reuse the stored DataFrame and LRU-touch the session. On a
    MISS: load via `_load_dataframe`, store it, and bound the cache to
    `_SESSION_CACHE_MAX` sessions (evict the oldest on overflow).
    """
    entry = _session_cache.get(session_id)
    if entry is None:
        entry = {"frames": {}, "order": []}
        _session_cache[session_id] = entry

    # LRU-touch the session (move to most-recent).
    _session_cache.pop(session_id, None)
    _session_cache[session_id] = entry

    frames: dict[str, pd.DataFrame] = entry["frames"]
    if dataset_id in frames:
        logger.info("session_cache_hit", session_id=session_id, dataset_id=dataset_id)
        return frames[dataset_id]

    frame = _load_dataframe(dataset_id)
    frames[dataset_id] = frame
    if dataset_id not in entry["order"]:
        entry["order"].append(dataset_id)
    logger.info("session_cache_miss", session_id=session_id, dataset_id=dataset_id)

    # Bound the number of cached sessions (evict the oldest).
    while len(_session_cache) > _SESSION_CACHE_MAX:
        oldest = next(iter(_session_cache))
        _session_cache.pop(oldest, None)
        logger.info("session_cache_evict", session_id=oldest)

    return frame


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #


# C33 token economics: how many column names to PREVIEW per dataset in the
# catalog. The catalog is a lean MENU the agent picks from — it pays for only these
# few names per dataset on every ReAct iteration, then pulls the FULL column list on
# demand (`df{n}.columns.tolist()`) for the datasets it actually drills into.
# Sending every column of every dataset on every iteration is exactly the bloat this
# avoids (see spec/capabilities/auto-dataset-selection.md).
_CATALOG_COLUMN_PREVIEW = 6


def _catalog_block(idx: int, entry: dict[str, Any]) -> str:
    """One dataset's line in the prompt CATALOG: how to reference it + a LEAN schema.

    Names the variable the model loads it with (`df{n}` and, when distinct, the
    `<alias>`), the source filename, and its schema. By DEFAULT it lists every column
    (exactly the pre-C33 line). For a wide table it can instead show the total column
    COUNT + a PREVIEW of the first `_CATALOG_COLUMN_PREVIEW` names + a
    `(+K more — df{n}.columns)` pointer — but it adopts that compressed form ONLY when
    it is actually SHORTER than the full listing. So a catalog line is NEVER larger
    than a plain schema, yet collapses hard for the wide tables that dominate a big
    workspace's per-iteration prompt cost (the compression pays off exactly when it
    hides enough columns to beat the `(+K more)` pointer's fixed overhead).

    Metadata-only either way: dtypes and row-counts come from on-demand inspection
    the model runs once a dataset looks relevant (`df{n}.columns.tolist()` / `.head()`)
    — the whole point is to pick WITHOUT paying for every column of every dataset on
    every ReAct iteration (C33 token economics).
    """
    dfn = f"df{idx + 1}"
    alias = entry.get("alias")
    names = f"`{dfn}` (alias `{alias}`)" if alias and alias != dfn else f"`{dfn}`"
    columns = [str(c) for c in (entry.get("columns") or [])]
    filename = entry.get("filename", "")
    if not columns:
        line = f"- {names} — {filename} — columns unknown (inspect with `{dfn}.columns`)"
    else:
        # Default: list every column — identical to the pre-C33 line.
        line = full = f"- {names} — {filename}: {', '.join(columns)}"
        if len(columns) > _CATALOG_COLUMN_PREVIEW:
            # Wide enough to consider compressing: COUNT + a preview of the first few
            # names + a pointer to the on-demand pull. Adopt it ONLY when it is
            # genuinely shorter than the full listing, so the line is never larger
            # than a plain schema — the saving is real precisely for the wide tables
            # that dominate a big workspace's prompt (C33 token economics).
            preview = ", ".join(columns[:_CATALOG_COLUMN_PREVIEW])
            hidden = len(columns) - _CATALOG_COLUMN_PREVIEW
            lean = (
                f"- {names} — {filename} — {len(columns)} cols: "
                f"{preview}, … (+{hidden} more — `{dfn}.columns` for all)"
            )
            if len(lean) < len(full):
                line = lean
    notes = (entry.get("notes") or "").strip()
    if notes:
        line += f"\n  notes: {notes}"
    return line


def setup(state: AgentState) -> AgentState:
    """Build the dataset CATALOG for the run — the agent picks + loads datasets lazily.

    Instead of eager-loading every dataset (the old pre-selected-subset model), this
    assembles a lightweight metadata-only catalog of ALL candidate datasets
    (filename, columns from `columns_json`, compressed notes) WITHOUT reading a
    single Parquet/CSV. Frames are materialised one at a time, the first time the
    model's expression references one (see `execute_action`'s loader +
    `build_lazy_namespace`), so a question that reads one table never loads the
    other twenty. The run-scoped bundle carries the catalog, a per-id frame cache
    (filled lazily), and any `save_dataset` outputs.

    C31: catalog notes use ONLY already-compressed `context_facts` — never raw notes,
    and setup does NOT trigger on-demand compression (it now spans EVERY dataset, so
    a compress-per-dataset storm on the first turn is exactly what a lazy catalog is
    meant to avoid). Datasets whose facts aren't cached yet simply show columns only.
    """
    run_id = state.get("run_id", "")
    session_id = state.get("session_id")
    dataset_ids = state.get("dataset_ids") or []

    if not dataset_ids:
        return {**state, "error": "No datasets supplied to load."}

    catalog: list[dict[str, Any]] = []
    try:
        with create_db_session() as session:
            for dataset_id in dataset_ids:
                row = session.get(DatasetRow, dataset_id)
                if row is None:
                    # Deleted between resolution and setup — skip it rather than fail
                    # the whole run; the remaining datasets stay usable.
                    continue
                filename = row.filename or f"{dataset_id}.csv"
                stem = filename.rsplit(".", 1)[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                catalog.append(
                    {
                        "id": dataset_id,
                        "filename": filename,
                        "alias": _safe_alias(stem),
                        "columns": [str(c) for c in (row.columns_json or [])],
                        # C31: compressed facts only — never raw notes, no on-demand
                        # compression here (see the docstring).
                        "notes": _facts_as_notes(row.context_facts or []),
                    }
                )
    except Exception as exc:  # noqa: BLE001 — catalog build is metadata-only
        logger.warning("setup_catalog_failed", run_id=run_id, error=str(exc))
        return {**state, "error": f"Failed to read dataset catalog: {exc}"}

    if not catalog:
        return {**state, "error": "No datasets available to analyse."}

    _dataframes[run_id] = {
        "session_id": session_id,
        "catalog": catalog,
        "frames": {},  # dataset_id -> DataFrame, filled lazily by execute_action
        "derived_frames": {},  # <alias> -> DataFrame (save_dataset outputs)
    }
    dataset_context = "\n\n".join(
        _catalog_block(idx, entry) for idx, entry in enumerate(catalog)
    )
    wants_chart = _wants_chart(state.get("question", ""))
    logger.info(
        "setup_ok",
        run_id=run_id,
        datasets=len(catalog),
        session=bool(session_id),
        wants_chart=wants_chart,
    )
    return {
        **state,
        "dataset_context": dataset_context,
        "status": "running",
        "wants_chart": wants_chart,
    }


# The fixed instruction footer appended to every assembled plan prompt.
_PLAN_FOOTER = (
    "Now reply with EITHER an action — an optional `REASONING:` line then a "
    "single bare pandas expression to run next, just the raw code, with NO "
    "backticks, NO ```python fence, and NO surrounding prose — OR "
    "`FINAL ANSWER:` followed by your answer."
)


def _plan_prompt_sections(state: AgentState, wrap_up: bool) -> dict[str, str]:
    """Build the per-section TEXT of the assembled plan_action user prompt.

    Returns a dict mapping a stable section key to its rendered text (empty string
    when the section is absent). The keys partition the WHOLE assembled user prompt
    with no overlap — `_assemble_plan_prompt` joins the non-empty ones, and
    `_plan_prompt_chars` measures them into the five C29 buckets. The `tag`,
    `question`, `wrap_up`, and `footer` keys are the fixed scaffolding; `datasets`,
    `memory`, `history`, and `actions` are the variable context blocks.

    NOTE: `dataset_context` is the metadata-only CATALOG built in `setup`, which
    folds each dataset's notes INTO its catalog line (via `_catalog_block`), so the
    `## Datasets` section (measured into `dataset_schemas`) already includes dataset
    notes — there is no separate `dataset_notes` bucket. See
    spec/capabilities/context-window-display.md.
    """
    sections: dict[str, str] = {}

    sections["tag"] = _PLAN_TAG

    dataset_context = state.get("dataset_context")
    sections["datasets"] = ("## Datasets\n" + dataset_context) if dataset_context else ""

    # Global persistent memory (slice-3c) is authoritative in every plan prompt,
    # injected only when non-empty. Read defensively so a 3c failure can't crash
    # planning.
    memory_block = _safe_memory_block()
    sections["memory"] = ("## Persistent memory\n" + memory_block) if memory_block else ""

    conversation_history = state.get("conversation_history") or []
    if conversation_history:
        convo = "\n".join(
            f"Q: {turn.get('question', '')}\nA: {turn.get('answer', '')}"
            for turn in conversation_history
        )
        sections["history"] = "## Earlier in this conversation\n" + convo
    else:
        sections["history"] = ""

    sections["question"] = "## Question\n" + (state.get("question") or "")

    action_history = state.get("action_history") or []
    if action_history:
        transcript_lines: list[str] = []
        for step in action_history:
            transcript_lines.append(f"Action: {step.get('action', '')}")
            if step.get("is_error"):
                transcript_lines.append(f"Error: {step.get('result', '')}")
            else:
                transcript_lines.append(f"Result: {step.get('result', '')}")
        sections["actions"] = "## Actions so far\n" + "\n".join(transcript_lines)
    else:
        sections["actions"] = ""

    if wrap_up:
        sections["wrap_up"] = (
            "## Wrap up now\n"
            "You are running low on steps. Do NOT run another action. Reply with "
            "`FINAL ANSWER:` and your best Markdown answer from the results above."
        )
    else:
        sections["wrap_up"] = ""

    sections["footer"] = _PLAN_FOOTER
    return sections


# The order the assembled prompt joins its sections in (matches the original
# `_assemble_plan_prompt` ordering exactly).
_PLAN_SECTION_ORDER = (
    "tag",
    "datasets",
    "memory",
    "history",
    "question",
    "actions",
    "wrap_up",
    "footer",
)


# Deterministic chart-guardrail reminder: appended to the plan prompt when the
# user explicitly asked for a chart but none has been produced yet.
_CHART_REQUIRED_REMINDER = (
    "## A chart is REQUIRED\n"
    "The user asked for a chart but none has been produced yet. Your NEXT action "
    "MUST be an `echart(...)` call (a bare expression). Do NOT reply "
    "`FINAL ANSWER:` until at least one chart has been produced."
)


def _assemble_plan_prompt(state: AgentState, wrap_up: bool) -> str:
    """Build the plan_action user prompt from question + transcript + context."""
    sections = _plan_prompt_sections(state, wrap_up)
    parts = [sections[key] for key in _PLAN_SECTION_ORDER if sections.get(key)]
    if state.get("wants_chart") and not state.get("charts"):
        parts.append(_CHART_REQUIRED_REMINDER)
    return "\n\n".join(parts)


def _plan_system_prompt(state: AgentState, system: str) -> str:
    """The plan_action system prompt, with the C35 Fast Mode brevity instruction
    appended conditionally (never a hard output-token cap — prompt guidance only).
    """
    if state.get("fast_mode"):
        return (system or "") + _FAST_MODE_BREVITY_LINE
    return system


# The five C29 buckets, in the order the breakdown reports them.
_PLAN_COMPONENT_KEYS = (
    "system_overhead",
    "dataset_schemas",
    "memory",
    "history",
    "action_history",
)


def _plan_prompt_chars(
    state: AgentState, wrap_up: bool, system_text: str
) -> dict[str, int]:
    """C29: partition THIS iteration's assembled plan prompt + system template into
    the five buckets, measured in raw CHARS (not tokens).

    The five keys partition the WHOLE prompt (system template `plan_action.md` plus
    every section of the assembled user prompt) with NO overlap and NO omission. The
    runner accumulates these across all iterations and then scales the cumulative
    char counts to the real cumulative provider `tokens_input`.

      - system_overhead = system template + fixed scaffolding (tag + question +
        wrap-up + instruction footer). All the fixed pieces and the question.
      - dataset_schemas = the `## Datasets` section (dataset notes are folded in
        here, not counted separately — counting them again would double-count).
      - memory          = the `## Persistent memory` section.
      - history         = the `## Earlier in this conversation` section.
      - action_history  = the `## Actions so far` section.
    """
    s = _plan_prompt_sections(state, wrap_up)
    system_overhead = (
        len(system_text or "")
        + len(s["tag"])
        + len(s["question"])
        + len(s["wrap_up"])
        + len(s["footer"])
    )
    return {
        "system_overhead": system_overhead,
        "dataset_schemas": len(s["datasets"]),
        "memory": len(s["memory"]),
        "history": len(s["history"]),
        "action_history": len(s["actions"]),
    }


def _accumulate_component_chars(
    prior: dict | None, this_iter: dict[str, int]
) -> dict[str, int]:
    """ADD this iteration's per-bucket char counts into the cumulative dict.

    Defensive: a missing/empty prior dict starts every bucket at zero, and any
    bucket absent from `prior` is treated as 0.
    """
    prior = prior or {}
    return {
        key: int(prior.get(key, 0)) + int(this_iter.get(key, 0))
        for key in _PLAN_COMPONENT_KEYS
    }


def plan_action(state: AgentState) -> AgentState:
    """Ask the LLM for the next pandas action or a FINAL ANSWER."""
    # User pressed Stop: skip the planning LLM call; after_plan routes to
    # force_finalize (which also short-circuits) so the run wraps up with no
    # further model calls.
    if is_cancelled(state.get("run_id", "")):
        return {**state, "llm_response": ""}

    iteration = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 6)
    wrap_up = iteration >= max_iterations - 2

    try:
        system = _load_prompt(_PLAN_PROMPT_PATH)
        # C35 Fast Mode: append the brevity instruction line to the system prompt
        # when active (prompt-level guidance only, never a hard token cap).
        system = _plan_system_prompt(state, system)
        prompt = _assemble_plan_prompt(state, wrap_up)
        # C29: measure THIS iteration's per-bucket char counts and ADD them into the
        # cumulative dict on state, so the runner's prompt_breakdown describes the
        # CUMULATIVE input composition of the whole query (aligned with "Last query In").
        this_iter_chars = _plan_prompt_chars(state, wrap_up, system)
        prompt_component_chars = _accumulate_component_chars(
            state.get("prompt_component_chars"), this_iter_chars
        )
        resp = LLMClient().complete(prompt, system=system)
    except Exception as exc:  # noqa: BLE001 — fatal LLM error
        logger.warning("plan_action_failed", run_id=state.get("run_id"), error=str(exc))
        return {**state, "error": f"LLM call failed: {exc}"}

    reply = resp.text or ""
    # Prefer the provider's REAL token usage; fall back to the chars/4 estimate
    # only when a provider reports none (e.g. usage metadata missing).
    in_toks = resp.tokens_input or (_estimate_tokens(prompt) + _estimate_tokens(system))
    out_toks = resp.tokens_output or _estimate_tokens(reply)
    tokens_input = state.get("tokens_input", 0) + in_toks
    tokens_output = state.get("tokens_output", 0) + out_toks

    is_final = "final answer:" in reply.lower()

    # Chart guardrail: a FINAL answer that arrives with no chart, when the user
    # explicitly asked for one, counts as a rejected finalize. Incrementing here
    # lets `after_plan` cap the number of forced retries (termination guarantee).
    chart_force_count = state.get("chart_force_count", 0)
    if is_final and state.get("wants_chart") and not state.get("charts"):
        chart_force_count += 1

    logger.info(
        "plan_action",
        run_id=state.get("run_id"),
        iteration=iteration + 1,
        is_final=is_final,
        chart_force_count=chart_force_count,
    )
    return {
        **state,
        "llm_response": reply,
        "iteration_count": iteration + 1,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "prompt_component_chars": prompt_component_chars,
        "chart_force_count": chart_force_count,
    }


# Leading `REASONING:` marker (case-insensitive, optional leading whitespace) that
# a planner reply may prefix its action with (C33 per-step reasoning).
_REASONING_RE = re.compile(r"^[ \t]*reasoning[ \t]*:", re.IGNORECASE)


def _split_reasoning(text: str) -> tuple[str, str]:
    """Split an OPTIONAL leading `REASONING:` line off a planner reply (C33).

    If the FIRST non-empty line, after optional leading whitespace, starts with the
    `REASONING:` marker (case-insensitive), returns
    `(reasoning, remainder)` where `reasoning` is the trimmed text after the marker
    on that line and `remainder` is everything AFTER that first line (unchanged).
    Otherwise returns `("", text)` with the ORIGINAL text untouched, so a bare
    expression reply (today's behaviour, and the stub's `df.describe().to_string()`)
    flows through `_extract_code` byte-for-byte as it does today.
    """
    if not text:
        return "", text
    lines = text.splitlines(keepends=True)
    # Find the first non-empty (non-whitespace-only) line.
    for idx, line in enumerate(lines):
        if line.strip():
            match = _REASONING_RE.match(line)
            if not match:
                return "", text
            reasoning = line[match.end():].strip()
            remainder = "".join(lines[idx + 1:])
            return reasoning, remainder
    # All-blank reply: no reasoning, original text unchanged.
    return "", text


# A ```python … ``` (or bare ``` … ```) fenced code block. Some models wrap the
# action in a fence — often after a few lines of reasoning prose — instead of the
# bare expression the prompt asks for.
_CODE_FENCE_RE = re.compile(r"```[ \t]*(?:python|py)?[ \t]*\r?\n?(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_code(text: str) -> str:
    """Pull the runnable pandas code out of a planner reply.

    The plan prompt asks for a single BARE expression, and capable models comply
    (so the reply IS the code). But some models (e.g. gemini-2.5-flash-lite) add
    reasoning prose and wrap the code in a ```python fence. Passing that prose to
    eval() raises spurious SyntaxErrors — an apostrophe in "turn's" reads as an
    unterminated string literal — so the model's actual code never runs.

    When the reply contains fenced block(s) we return the LAST non-empty one (the
    step's intended action); otherwise the stripped reply is used as-is. This keeps
    the executor model-agnostic without constraining well-behaved models.
    """
    if not text:
        return ""
    blocks = _CODE_FENCE_RE.findall(text)
    for block in reversed(blocks):
        if block.strip():
            return _strip_inline_ticks(block.strip())
    return _strip_inline_ticks(text.strip())


def _strip_inline_ticks(s: str) -> str:
    """Strip inline-code backticks a model wrapped a bare expression in (`expr`).

    Some models emit the action as inline code — e.g. `` `df.columns.tolist()` `` —
    which is not valid Python. When the whole (single-line) reply is fenced in
    backticks we peel them off; multi-line text is left alone (a real code block,
    handled by the fence regex, or genuine content).
    """
    s = s.strip()
    if "\n" not in s and s.startswith("`") and s.endswith("`"):
        return s.strip("`").strip()
    return s


def execute_action(state: AgentState) -> AgentState:
    """Eval the model's pandas expression in the sandbox; record the step.

    On exception: mark `is_error=true`, record the error, route back to plan_action
    (recoverable). Charts are captured into `charts`. `iteration_count` is written
    to the DB each step for live polling.

    The planner reply is run through `_extract_code` first, so a model that wraps
    its action in a ```python fence (with reasoning prose around it) still has its
    REAL code executed instead of eval() choking on the prose.

    An OPTIONAL leading `REASONING:` line (C33) is split off the raw reply BEFORE
    `_extract_code` runs, so the executed expression is byte-for-byte what it is for
    a bare reply; the rationale is recorded on the step (default `""`).
    """
    run_id = state.get("run_id", "")
    reasoning, remainder = _split_reasoning(state.get("llm_response", ""))
    expr = _extract_code(remainder)
    action_history = list(state.get("action_history") or [])
    charts = list(state.get("charts") or [])

    # The agent picks datasets by REFERENCING them: `build_lazy_namespace` maps
    # `df{n}`/alias names to dataset ids and materialises a frame only when the
    # model's expression first touches that name (via the `_loader` closure below),
    # so a question that reads one table never loads the other twenty.
    bundle = _dataframes.get(run_id) or {
        "session_id": state.get("session_id"),
        "catalog": [],
        "frames": {},
        "derived_frames": {},
    }
    session_id = bundle.get("session_id")
    frames_cache: dict[str, pd.DataFrame] = bundle["frames"]

    def _loader(dataset_id: str) -> pd.DataFrame:
        """Materialise (and cache) one dataset the first time the agent references it.

        Records the id in `_loaded_ids[run_id]` — the used-tracking that becomes the
        run's real `dataset_ids` (accurate "Datasets used", correct C15 cascade) and
        doubles as save_dataset's parent lineage. Uses the session cache (C27) for a
        multi-turn conversation, else the simple per-run load.
        """
        cached = frames_cache.get(dataset_id)
        if cached is not None:
            return cached
        frame = (
            _session_load_frame(session_id, dataset_id)
            if session_id
            else _load_dataframe(dataset_id)
        )
        frames_cache[dataset_id] = frame
        touched = _loaded_ids.setdefault(run_id, [])
        if dataset_id not in touched:
            touched.append(dataset_id)
        return frame

    namespace = build_lazy_namespace(bundle["catalog"], _loader, bundle["derived_frames"])

    # Override the module-level stub with a run-aware `save_dataset` that knows the
    # producing run_id + parent dataset_ids and records each created derived id
    # (C25). The closure captures the current action expression as derivation_code
    # via `eval_expression` (it calls `.set_code` before eval).
    def _on_registered(new_id: str) -> None:
        _derived_created.setdefault(run_id, []).append(new_id)

    def _on_saved(name: str, df: pd.DataFrame) -> None:
        # Make a save_dataset'd frame referenceable as `<name>` (v0.5 parity):
        # record it in the run's derived_frames so the NEXT step's lazy namespace
        # resolves it via `__missing__`, and inject it into the CURRENT action's
        # namespace so a later statement in the same action can use it. A re-save of
        # the same name replaces the prior frame (latest wins).
        alias = _safe_alias(name) or name
        bundle["derived_frames"][alias] = df
        namespace[alias] = df

    namespace["save_dataset"] = make_save_dataset(
        run_id=run_id,
        # The LIVE loaded-ids list: `make_save_dataset` snapshots it at CALL time
        # (`list(parent_ids or [])` inside the closure), so a save records exactly the
        # datasets loaded up to that point as its parent lineage.
        parent_ids=_loaded_ids.setdefault(run_id, []),
        on_registered=_on_registered,
        on_saved=_on_saved,
    )

    # Run-aware `echart(...)`: each call appends the built ECharts `option` dict to
    # this per-action accumulator (C4). We `json.dumps` each captured option and
    # append to `state["charts"]` (the unchanged `query_runs.charts_json` shape —
    # an array of JSON strings; only the CONTENT is now an ECharts option).
    captured_options: list[dict[str, Any]] = []

    def _on_chart(option: dict[str, Any]) -> None:
        captured_options.append(option)

    namespace["echart"] = make_echart(on_chart=_on_chart)

    result_str, _ignored_charts, is_error, error_str = eval_expression(expr, namespace)
    for option in captured_options:
        try:
            charts.append(json.dumps(option))
        except Exception as exc:  # noqa: BLE001 — a bad option must not crash the run
            logger.warning("chart_serialize_failed", run_id=run_id, error=str(exc))

    step_result = error_str if is_error else result_str
    # C35 Fast Mode: truncate the STORED/re-transmitted result AFTER the
    # error/non-error string is chosen (so it never affects is_error detection),
    # immediately before the step is appended (so it compounds correctly across
    # iterations — each later prompt re-sends the already-shortened result). The
    # UI shows this same (truncated) string, so there is no "model saw less than
    # what I see" mismatch.
    if state.get("fast_mode"):
        step_result = _truncate_result(step_result)

    step = {
        "action": expr,
        "result": step_result,
        "is_error": is_error,
        "reasoning": reasoning,
    }
    action_history.append(step)

    # Persist iteration_count each step for live progress polling (best-effort).
    try:
        with create_db_session() as session:
            row = session.get(QueryRunRow, run_id)
            if row is not None:
                row.iteration_count = state.get("iteration_count", 0)
                row.action_history = action_history
    except Exception as exc:  # noqa: BLE001 — polling write is non-fatal
        logger.warning("execute_action_db_write_failed", run_id=run_id, error=str(exc))

    logger.info("execute_action", run_id=run_id, is_error=is_error)
    return {**state, "action_history": action_history, "charts": charts}


def _strip_final_answer(text: str) -> str:
    """Strip a leading `FINAL ANSWER:` prefix (case-insensitive, tolerate preamble)."""
    if not text:
        return ""
    lower = text.lower()
    marker = "final answer:"
    idx = lower.find(marker)
    if idx == -1:
        return text.strip()
    return text[idx + len(marker):].strip()


def get_derived_created(run_id: str) -> list[str]:
    """Derived dataset ids created by `save_dataset` during `run_id` (C25).

    Read by the runner to surface `derived_dataset_ids` in the `/ask` payload.
    Returns a fresh copy; empty when nothing was saved (or already released).
    """
    return list(_derived_created.get(run_id, []))


def release_derived_created(run_id: str) -> None:
    """Drop the run's derived-id registry once the runner has read it."""
    _derived_created.pop(run_id, None)


def get_loaded_ids(run_id: str) -> list[str]:
    """The EXISTING dataset ids the agent actually loaded during `run_id`.

    This is the agent's dataset PICK — the runner records it as the run's real
    `dataset_ids` (accurate "Datasets used", correct C15 cascade-delete scope, and
    the session's dataset set). Survives `_release_dataframe` (kept in a separate
    registry), so the runner reads it AFTER the graph returns. Order is load order;
    empty when the agent loaded nothing (or already released).
    """
    return list(_loaded_ids.get(run_id, []))


def release_loaded_ids(run_id: str) -> None:
    """Drop the run's loaded-id registry once the runner has read it."""
    _loaded_ids.pop(run_id, None)


def _release_dataframe(run_id: str) -> None:
    _dataframes.pop(run_id, None)


def invalidate_dataset_cache(dataset_id: str) -> None:
    """Evict `dataset_id` from every session entry in `_session_cache` (C27/D2).

    Called after a dataset is mutated (clean/apply or re-derive) so subsequent
    multi-turn turns see the fresh on-disk data rather than the stale cached
    DataFrame. Empty session entries are removed to keep the cache compact.
    """
    stale_sessions = [
        sid for sid, entry in _session_cache.items()
        if dataset_id in entry.get("frames", {})
    ]
    for sid in stale_sessions:
        entry = _session_cache.get(sid)
        if entry is None:
            continue
        frames: dict = entry.get("frames", {})
        frames.pop(dataset_id, None)
        order: list = entry.get("order", [])
        try:
            order.remove(dataset_id)
        except ValueError:
            pass
        # If the session now has no cached frames, drop the session entry entirely.
        if not frames:
            _session_cache.pop(sid, None)
            logger.info("session_cache_evict_empty", session_id=sid)
        else:
            logger.info(
                "session_cache_invalidated",
                session_id=sid,
                dataset_id=dataset_id,
            )


def finalize(state: AgentState) -> AgentState:
    """Produce the final answer from the model's FINAL ANSWER reply."""
    run_id = state.get("run_id", "")
    answer = _strip_final_answer(state.get("llm_response", ""))
    _release_dataframe(run_id)
    logger.info("finalize", run_id=run_id, answer_len=len(answer))
    return {**state, "answer": answer, "status": "completed"}


def _build_transcript(action_history: list[dict]) -> str:
    lines: list[str] = []
    for step in action_history:
        lines.append(f"Action: {step.get('action', '')}")
        label = "Error" if step.get("is_error") else "Result"
        lines.append(f"{label}: {step.get('result', '')}")
    return "\n".join(lines)


def force_finalize(state: AgentState) -> AgentState:
    """Best-effort synthesis when the loop hits max-iter or consecutive errors.

    ONE synthesis LLM call; `status` is ALWAYS `completed`. Falls back to a static
    message if the call fails. Sets an informational `error_message`.
    """
    run_id = state.get("run_id", "")
    action_history = state.get("action_history") or []

    # User pressed Stop: wrap up WITHOUT a synthesis LLM call — that's the whole
    # point of stopping. Return a short marker; the run persists as completed.
    if is_cancelled(run_id):
        _release_dataframe(run_id)
        logger.info("force_finalize_cancelled", run_id=run_id)
        return {
            **state,
            "answer": "_Run stopped by the user before it finished._",
            "status": "completed",
            "error_message": "cancelled",
        }

    # Classify why we are wrapping up (informational, not a failure). Consecutive
    # errors take precedence over max-iter when both could apply.
    consecutive = 0
    for step in reversed(action_history):
        if step.get("is_error"):
            consecutive += 1
        else:
            break
    reason = "consecutive_errors" if consecutive >= _MAX_CONSECUTIVE_ERRORS else "max_iterations"

    try:
        system = _load_prompt(_FINALIZE_PROMPT_PATH)
        prompt = (
            f"{_FINALIZE_TAG}\n\n"
            f"## Question\n{state.get('question', '')}\n\n"
            f"## Transcript\n{_build_transcript(action_history)}\n\n"
            "Write the best-effort final answer in Markdown (no FINAL ANSWER: prefix)."
        )
        resp = LLMClient().complete(prompt, system=system)
        answer = (resp.text or "").strip() or _static_best_effort(state)
        in_toks = resp.tokens_input or (_estimate_tokens(prompt) + _estimate_tokens(system))
        out_toks = resp.tokens_output or _estimate_tokens(answer)
        tokens_input = state.get("tokens_input", 0) + in_toks
        tokens_output = state.get("tokens_output", 0) + out_toks
    except Exception as exc:  # noqa: BLE001 — fall back to a static message
        logger.warning("force_finalize_llm_failed", run_id=run_id, error=str(exc))
        answer = _static_best_effort(state)
        tokens_input = state.get("tokens_input", 0)
        tokens_output = state.get("tokens_output", 0)

    _release_dataframe(run_id)
    logger.info("force_finalize", run_id=run_id, reason=reason)
    return {
        **state,
        "answer": answer,
        "status": "completed",
        "error_message": reason,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
    }


def _static_best_effort(state: AgentState) -> str:
    return (
        "I was not able to fully complete the analysis within the available steps. "
        "Based on the work done so far, here is a best-effort summary; please try "
        "rephrasing or narrowing the question for a more precise answer."
    )


def handle_error(state: AgentState) -> AgentState:
    """Fatal error: mark the run failed, keep the message, release the DataFrame."""
    run_id = state.get("run_id", "")
    _release_dataframe(run_id)
    logger.warning("handle_error", run_id=run_id, error=state.get("error"))
    return {**state, "status": "failed", "error_message": state.get("error")}
