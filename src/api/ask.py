"""`POST /ask` — run a session-scoped analysis (Phase 3).

Phase-3 scope (the full `spec/api.md` `/ask` contract):

- Every `/ask` belongs to a *session*. An explicit `session_id` resumes a
  conversation (enforcing the 20-turn cap); without one, a fresh
  `ConversationSessionRow` is created.
- Dataset selection is AGENT-DRIVEN: there is no manual scoping. Every `/ask`
  hands the runner ALL of the workspace's datasets and the agent picks (and
  lazily loads) whichever it needs. The request's `dataset_id`/`dataset_ids`
  fields are retained for API compatibility but no longer scope the run.
- Multi-turn: prior completed turns of the session are assembled into
  `conversation_history` and passed to the runner.
- Pre-flight clarification (C26): on the FIRST turn (no `session_id`), unless
  `skip_clarification`, the runner may short-circuit and return
  `type:"clarification"` — we relay that payload and the runner owns the thin
  `query_runs` row it created.
- Answer path: the full answer payload, with `answer_html` rendered from the
  Markdown, the real `session_id`, suggestions, and prompt breakdown. The
  session's dataset set accumulates the datasets the agent actually USED plus any
  it DERIVED, so the sidebar/continuity reflect real dependencies.

Run-row creation is owned by `run_agent` (it has been since Phase 2) — this
route never duplicates it.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from markdown_it import MarkdownIt
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api._common import ok, api_error
from db.models import ConversationSessionRow, DatasetRow, QueryRunRow
from db.session import create_db_session, get_session
from domain.ask import AskRequest
from graph.runner import run_agent

router = APIRouter()

_md = MarkdownIt()

# A session is capped at 20 settled turns (spec/roadmap.md "Conversation cap").
_TURN_LIMIT = 20

# Statuses that count as a settled turn against the cap / for history assembly.
_TURN_STATUSES = ("completed", "failed", "clarification")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_dataset_filenames(dataset_ids: list[str]) -> list[str]:
    """Map dataset ids -> their `DatasetRow.filename` for display (`datasets_used`).

    One session, one loop. If a row is missing (deleted/unknown id), fall back to
    the id itself so the list stays aligned with `dataset_ids`.
    """
    if not dataset_ids:
        return []
    names: list[str] = []
    with create_db_session() as session:
        for did in dataset_ids:
            row = session.get(DatasetRow, did)
            names.append(row.filename if row is not None and row.filename else did)
    return names


def _count_turns(session: Session, session_id: str) -> int:
    return session.execute(
        select(func.count())
        .select_from(QueryRunRow)
        .where(QueryRunRow.session_id == session_id)
        .where(QueryRunRow.status.in_(_TURN_STATUSES))
    ).scalar_one()


def _conversation_history(session: Session, session_id: str) -> list[dict]:
    """Prior COMPLETED turns of the session, oldest-first, as {question, answer}."""
    rows = (
        session.execute(
            select(QueryRunRow)
            .where(QueryRunRow.session_id == session_id)
            .where(QueryRunRow.status == "completed")
            .order_by(QueryRunRow.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [{"question": r.question, "answer": r.answer or ""} for r in rows]


@router.post("/ask")
def ask(req: AskRequest, session: Session = Depends(get_session)) -> dict:
    question = (req.question or "").strip()
    if not question:
        raise api_error("empty_question", "Question must not be empty.", 400)

    # Dataset selection is agent-driven: hand the runner EVERY dataset in the
    # workspace and let the agent pick (and lazily load) whichever it needs. The
    # request's dataset fields no longer scope the run (see module docstring).
    # Order by upload time (oldest first) so the catalog's `df1`/`df2`/... numbering
    # is deterministic and stable across turns — it mirrors the order the user added
    # the tables. Without an explicit ORDER BY, `select(id)` is served from the id
    # primary-key index and comes back in random UUID order, so `df1` would point at
    # an arbitrary table each run.
    candidate_ids = list(
        session.execute(
            select(DatasetRow.id).order_by(DatasetRow.created_at.asc())
        ).scalars().all()
    )
    if not candidate_ids:
        raise api_error(
            "no_datasets", "No datasets uploaded yet. Upload a file first.", 400
        )

    # --- Session resolution ------------------------------------------------
    # Clarification (C26) is a first-turn concern: run it only when starting a new
    # conversation, skip it on follow-ups (the history disambiguates).
    session_row: ConversationSessionRow | None = None
    run_clarification = True
    if req.session_id:
        session_row = session.get(ConversationSessionRow, req.session_id)
        if session_row is None:
            raise api_error("not_found", f"Session {req.session_id} not found", 404)

        # 20-turn cap.
        if _count_turns(session, session_row.id) >= _TURN_LIMIT:
            raise api_error(
                "turn_limit", "Session has reached the 20-turn limit.", 400
            )
        run_clarification = False

    # --- Ensure a session exists for this turn ----------------------------
    # A new session starts with NO datasets — its set accumulates the datasets the
    # agent actually uses (and derives) as turns run, so deleting a dataset only
    # cascades to conversations that truly depend on it (C15).
    if session_row is None:
        session_row = ConversationSessionRow(
            dataset_id=None,
            dataset_ids_json=[],
            name=None,
        )
        session.add(session_row)
        session.flush()  # assign the id before we hand it to the runner
    session_id = session_row.id

    # --- Multi-turn history (prior completed turns) -----------------------
    history = _conversation_history(session, session_id)

    # Release this request's write transaction BEFORE invoking the runner.
    # `run_agent` opens its own connection to insert/update the `query_runs`
    # row; under SQLite a still-open write lock here would deadlock that write
    # ("database is locked"). Committing the session row first frees the lock
    # and durably persists the session even if the run later fails.
    session.commit()

    # --- Run the agent (run-row creation lives in run_agent) --------------
    # Wall-clock the run so the UI can show the answer's response time. This
    # spans the whole agent loop (clarification + iterations + finalize), which is
    # the "how long did my answer take" the user cares about.
    _t0 = time.monotonic()
    result = run_agent(
        question,
        candidate_ids,
        session_id=session_id,
        conversation_history=history,
        skip_clarification=req.skip_clarification,
        run_clarification=run_clarification,
        max_iterations=None,
        fast_mode=req.fast_mode,
    )
    duration_ms = int((time.monotonic() - _t0) * 1000)

    # Bump the session's recency so the sidebar orders by last activity. The
    # row was committed/expired above; re-load it in this session to update.
    session_row = session.get(ConversationSessionRow, session_id)
    if session_row is not None:
        session_row.updated_at = _now()
        # Accumulate the datasets this turn actually touched into the session's set:
        # the ones the agent USED (its pick) plus any it DERIVED via save_dataset.
        # This keeps continuity (a follow-up can reference a saved frame by name)
        # and scopes the C15 cascade to real dependencies. A clarification turn
        # contributes nothing (no used/derived ids), leaving the set unchanged.
        touched = [
            *(result.get("dataset_ids") or []),
            *(result.get("derived_dataset_ids") or []),
        ]
        if touched:
            current = list(session_row.dataset_ids_json or [])
            for did in touched:
                if did and did not in current:
                    current.append(did)
            session_row.dataset_ids_json = current
            if session_row.dataset_id is None and current:
                session_row.dataset_id = current[0]

    # --- Clarification short-circuit (C26) --------------------------------
    if result.get("type") == "clarification":
        return ok(
            {
                "type": "clarification",
                "clarification_question": result.get("clarification_question"),
                # C37: up to 3 refined candidate questions from the SAME single
                # pre-flight call ([] on a plain-text fallback; live-only).
                "suggested_questions": result.get("suggested_questions") or [],
                "run_id": result["run_id"],
                "session_id": session_id,
                "status": "clarification",
                "fast_mode": req.fast_mode,
            }
        )

    # --- Answer path ------------------------------------------------------
    answer_markdown = result.get("answer") or ""
    answer_html = _md.render(answer_markdown) if answer_markdown else ""
    # The runner returns the ids the agent ACTUALLY loaded (its pick) — that is the
    # run's real dataset set. Empty when the agent loaded nothing.
    used_ids = result.get("dataset_ids") or []
    # `dataset_ids` carries the raw ids (session/continuity); `datasets_used` is
    # the human-readable list of filenames the UI renders. Resolve ids -> names
    # in one session/loop, falling back to the id itself if a row is missing.
    datasets_used_names = _resolve_dataset_filenames(used_ids)

    return ok(
        {
            "type": "answer",
            "run_id": result["run_id"],
            "session_id": session_id,
            "dataset_ids": used_ids,
            "derived_dataset_ids": result.get("derived_dataset_ids") or [],
            "datasets_used": datasets_used_names,
            "selector_reasoning": result.get("selector_reasoning"),
            "answer_markdown": answer_markdown,
            "answer_html": answer_html,
            "charts": result.get("charts") or [],
            "iteration_count": result.get("iteration_count", 0),
            "tokens_input": result.get("tokens_input", 0),
            "tokens_output": result.get("tokens_output", 0),
            # C39: payload-level sibling field — NEVER a key inside prompt_breakdown
            # (the breakdown component renders unknown keys as bars).
            "tokens_cached": result.get("tokens_cached", 0),
            "status": result.get("status", "completed"),
            "is_best_effort": result.get("is_best_effort", False),
            "steps": result.get("action_history") or [],
            "suggested_questions": result.get("suggested_questions") or [],
            "prompt_breakdown": result.get("prompt_breakdown") or {},
            "duration_ms": duration_ms,
            "fast_mode": req.fast_mode,
        }
    )
