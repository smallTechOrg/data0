"""`/suggestions` routes (Phase 10, C37) — session-start starter questions.

`spec/api.md` -> "### `GET /suggestions/starters`": the "Try asking:" chips shown
when the Analyse conversation is empty. Session-less (no params, no body — chips
seed the composer BEFORE any session exists) and NEVER a 5xx:

- empty workspace -> 200 `{questions: []}` BEFORE any LLM call;
- LLM error / unparseable reply / offline stub -> 200 `{questions: []}`.

The catalog is METADATA-ONLY, mirroring `setup`'s catalog build (`graph.nodes`):
filenames + `datasets.columns_json` + compressed `context_facts` rendered via the
same `_facts_as_notes` convention — NO DataFrames are loaded and no data files are
read, so the endpoint stays cheap enough to hit on every empty-tab view. The one
LLM call belongs to NO run: its tokens are not attributed to `query_runs` /
`GET /stats/daily` (documented, accepted gap). Not Fast-Mode-gated (`fast_mode`
is a per-`/ask` flag; starters precede any query). Contract:
`spec/capabilities/suggested-questions.md`.
"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from api._common import ok
from db.models import DatasetRow
from db.session import create_db_session
from graph.nodes import _facts_as_notes
from graph.suggestions import generate_starter_questions
from observability.events import get_logger

logger = get_logger("api.suggestions")

router = APIRouter()

# Cap the notes fragment per dataset line (same discipline as the runner's
# clarification schemas block) so a fact-heavy workspace can't bloat the prompt.
_NOTES_MAX_CHARS = 300


def _catalog_text() -> str:
    """Build the metadata-only dataset catalog for the starters prompt.

    One line per dataset: filename + columns (from `columns_json`) + compressed
    `context_facts` notes (rendered facts-first via `_facts_as_notes`, exactly
    the `setup` convention — raw `context` notes are NEVER sent; a dataset with
    no cached facts shows columns only). Reads ONLY the `datasets` rows — no
    frame/file access. Empty string on an empty workspace.
    """
    parts: list[str] = []
    with create_db_session() as session:
        rows = (
            session.execute(select(DatasetRow).order_by(DatasetRow.created_at.desc()))
            .scalars()
            .all()
        )
        for row in rows:
            columns = ", ".join(str(c) for c in (row.columns_json or []))
            line = f"- {row.filename}: columns [{columns}]"
            notes = _facts_as_notes(row.context_facts or [])
            if notes:
                line += f"; notes: {notes[:_NOTES_MAX_CHARS]}"
            parts.append(line)
    return "\n".join(parts)


@router.get("/suggestions/starters")
def get_starter_suggestions() -> dict:
    """C37 starter questions for an empty conversation. ALWAYS 200, never a 5xx.

    Empty workspace -> `{questions: []}` without any LLM call. Otherwise ONE
    `generate_starter_questions` call (tag `<node:suggest>`), which itself never
    raises; a defensive catch keeps even a catalog-build failure at 200.
    """
    try:
        catalog = _catalog_text()
        if not catalog.strip():
            # Empty workspace: short-circuit BEFORE any LLM call.
            return ok({"questions": []})
        questions = generate_starter_questions(catalog)
    except Exception as exc:  # noqa: BLE001 — never a 5xx; chips are optional
        logger.warning("starters_endpoint_failed", error=str(exc))
        questions = []
    return ok({"questions": questions})
