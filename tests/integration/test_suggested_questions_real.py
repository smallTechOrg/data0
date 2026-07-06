"""Real-Gemini integration tests for slice-10a (C37) — suggested questions.

Requires `AGENT_GEMINI_API_KEY` in `.env` (auto-detect selects the real Gemini
provider). These tests drive the REAL model, per the deferred-verification
criteria in `spec/capabilities/suggested-questions.md` -> Success Criteria ->
Real-key:

- `GET /suggestions/starters` with real datasets present returns 1-3 non-empty
  questions that reference actual dataset content (column names / topics from
  the metadata catalog).
- An ambiguous first-turn question returns a clarification with a clarifying
  question AND 1-3 refined candidates, produced by EXACTLY ONE `<node:clarify>`
  LLM call (counted via a wrapping client — no extra roundtrip).
- Submitting one of the returned refined candidates proceeds to a real
  `type:"answer"` (the candidates are genuinely runnable questions).

NOTE (Phase 10 gate): the RUN of this file is deferred until the Gemini daily
quota resets (see `spec/roadmap.md` -> Phase 10 gate + Backlog "Real-key
test-suite pacing"); the offline suite is the authoritative gate today.
"""
from __future__ import annotations

import pandas as pd
import pytest

from db.models import DatasetRow
from db.session import create_db_session
from graph import nodes as nodes_module
from graph.runner import run_agent


@pytest.fixture(autouse=True)
def uploads_dir(tmp_path, monkeypatch):
    """Point BOTH the nodes' and the runner's uploads dir at a tmp dir."""
    import graph.runner as runner_module

    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: d)
    monkeypatch.setattr(runner_module, "_uploads_dir", lambda: d)
    return d


@pytest.fixture(autouse=True)
def _clear_session_cache():
    nodes_module._session_cache.clear()
    yield
    nodes_module._session_cache.clear()


def _make_dataset(
    uploads_dir,
    filename: str,
    df: pd.DataFrame,
    context_facts: list[str] | None = None,
) -> str:
    with create_db_session() as session:
        row = DatasetRow(
            filename=filename,
            file_path="",
            row_count=len(df),
            col_count=len(df.columns),
            columns_json=list(df.columns),
            content_hash=f"hash-{filename}",
            format="csv",
            origin="uploaded",
            context_facts=context_facts,
        )
        session.add(row)
        session.flush()
        dataset_id = row.id
        csv_path = uploads_dir / f"{dataset_id}.csv"
        df.to_csv(csv_path, index=False)
        # also write parquet (preferred by the loader) to mirror production
        df.to_parquet(uploads_dir / f"{dataset_id}.parquet")
        row.file_path = str(csv_path)
    return dataset_id


_SALES = pd.DataFrame(
    {
        "region": ["north", "south", "east", "west"] * 3,
        "revenue": [1000.0, 2000.0, 1500.0, 2500.0] * 3,
        "units_sold": [10, 20, 15, 25] * 3,
        "month": ["jan"] * 4 + ["feb"] * 4 + ["mar"] * 4,
    }
)


# --------------------------------------------------------------------------- #
# Starters reference actual dataset content
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("_require_llm_key")
def test_starters_reference_real_dataset_content(api_client, uploads_dir):
    """With real datasets in the workspace, GET /suggestions/starters returns
    1-3 non-empty questions grounded in the catalog (columns/topics)."""
    _make_dataset(
        uploads_dir,
        "regional_sales.csv",
        _SALES,
        context_facts=["monthly revenue and units sold per region"],
    )

    r = api_client.get("/suggestions/starters")
    assert r.status_code == 200, r.text
    questions = r.json()["data"]["questions"]

    print(f"\n[starters] real Gemini proposed: {questions}")
    assert 1 <= len(questions) <= 3, f"expected 1-3 starters, got {questions}"
    for q in questions:
        assert isinstance(q, str) and q.strip(), f"empty starter in {questions}"
        assert "[stub]" not in q, "got a stub reply — real provider not used"

    # Grounding: at least one question references actual dataset content —
    # a column name or an obvious catalog topic (tolerant across phrasings).
    topics = ("revenue", "region", "unit", "month", "sales")
    joined = " ".join(questions).lower()
    assert any(t in joined for t in topics), (
        f"starters should reference the catalog's columns/topics {topics}; "
        f"got {questions}"
    )


# --------------------------------------------------------------------------- #
# Clarification candidates: ONE <node:clarify> call, and candidates run to an
# answer (covers the remaining two real-key criteria in one quota-lean flow)
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("_require_llm_key")
def test_clarification_candidates_single_call_and_runnable(uploads_dir, monkeypatch):
    """An ambiguous first-turn question -> `type:"clarification"` with a
    clarifying question AND 1-3 refined candidates from EXACTLY ONE
    `<node:clarify>` call; submitting a returned candidate then proceeds to a
    real `type:"answer"`."""
    import graph.preflight as preflight_module
    import llm.client as llm_client_module

    dataset_id = _make_dataset(uploads_dir, "financials.csv", _SALES)

    clarify_calls: list[str] = []

    class _CountingClient(llm_client_module.LLMClient):
        def call_model(self, prompt, *, system=None):
            if "<node:clarify>" in (prompt or ""):
                clarify_calls.append(prompt)
            return super().call_model(prompt, system=system)

    monkeypatch.setattr(preflight_module, "LLMClient", _CountingClient)

    # Deliberately ambiguous: multiple numeric columns, none named.
    result = run_agent(
        "What is the average?",
        [dataset_id],
        run_clarification=True,
        skip_clarification=False,
    )

    assert result["type"] == "clarification", (
        f"expected a clarification for an ambiguous question, got "
        f"{result.get('type')} answer={result.get('answer')!r}"
    )
    assert len(clarify_calls) == 1, (
        f"the question + candidates must come from EXACTLY ONE <node:clarify> "
        f"call; counted {len(clarify_calls)}"
    )

    question = result["clarification_question"]
    assert question and question.strip(), "clarification_question must be non-empty"
    assert "[stub]" not in question, "got a stub reply — real provider not used"

    candidates = result["suggested_questions"]
    print(f"\n[clarification] question={question!r} candidates={candidates}")
    assert 1 <= len(candidates) <= 3, (
        f"expected 1-3 refined candidates from the extended reply; got {candidates}"
    )
    for c in candidates:
        assert isinstance(c, str) and c.strip(), f"empty candidate in {candidates}"

    # A tapped candidate is a genuinely runnable question: submitting it as the
    # next ask proceeds (no re-clarification) to a real answer.
    followup = run_agent(
        candidates[0],
        [dataset_id],
        run_clarification=True,
        skip_clarification=False,
    )
    assert followup["type"] == "answer", (
        f"a refined candidate must run to an answer, got {followup.get('type')} "
        f"(clarification_question={followup.get('clarification_question')!r})"
    )
    assert followup["status"] == "completed"
    answer = followup["answer"]
    assert answer and answer.strip(), "candidate run must yield a real answer"
    assert "[stub]" not in answer, "got a stub answer — real provider not used"
    print(f"[candidate run] answer length={len(answer)} status={followup['status']}")
