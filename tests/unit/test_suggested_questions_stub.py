"""Offline unit tests for slice-10a (C37) — suggested questions.

Zero env vars, no network, in-memory SQLite (via the autouse `_isolated_db`
fixture in conftest). Covers the Phase-10 offline gate
(`spec/capabilities/suggested-questions.md` -> Success Criteria -> Offline):

- `GET /suggestions/starters`: 200 `{questions: []}` under the stub provider;
  empty workspace short-circuits BEFORE any LLM call; an LLM error never 5xxes;
  the catalog is METADATA-ONLY (no frame/file reads).
- Extended C26 clarify parsing (`check_clarification`): JSON-object reply (bare
  and fenced) -> `ClarificationResult(question, <=3 suggestions)`; >3 capped;
  missing/invalid `suggestions` -> []; plain-text reply -> whole-reply fallback
  with []; empty-`question` JSON -> fallback; `proceed`/error contracts stay
  covered by the UNMODIFIED tests/unit/test_preflight_stub.py.
- `POST /ask` clarification payload carries `suggested_questions` (populated on
  a JSON reply, [] on a plain-text fallback) — a parse failure never blocks the
  clarification itself.

The REAL-Gemini behaviour is covered by
tests/integration/test_suggested_questions_real.py (deferred-verification).
"""
from __future__ import annotations

import io

import pandas as pd
import pytest

from db.models import DatasetRow
from db.session import create_db_session
from graph.preflight import ClarificationResult, check_clarification
from graph.suggestions import generate_starter_questions


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Make `LLMClient` use the offline stub provider for every test here."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    monkeypatch.delenv("AGENT_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_OPENROUTER_API_KEY", raising=False)


def _fake_llm(reply: str):
    """A stand-in LLMClient class whose call_model always returns `reply`."""

    class _Fake:
        def call_model(self, *a, **k):
            return reply

    return _Fake


def _make_dataset_row(
    filename: str = "sales.csv",
    columns: list[str] | None = None,
    context_facts: list[str] | None = None,
) -> str:
    """A `datasets` row with NO file on disk — metadata is all the C37 paths read."""
    cols = columns or ["product", "price", "qty"]
    with create_db_session() as session:
        row = DatasetRow(
            filename=filename,
            file_path="",
            row_count=4,
            col_count=len(cols),
            columns_json=cols,
            content_hash="hash-" + filename,
            format="csv",
            origin="uploaded",
            context_facts=context_facts,
        )
        session.add(row)
        session.flush()
        return row.id


# --------------------------------------------------------------------------- #
# GET /suggestions/starters — always 200, never 5xx
# --------------------------------------------------------------------------- #


def test_starters_stub_returns_empty_list_200(api_client):
    """>=1 dataset present, stub provider: the `<node:suggest>` branch returns
    "[]" -> 200 `{questions: []}` in the `ok(...)` envelope."""
    _make_dataset_row()
    r = api_client.get("/suggestions/starters")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["data"] == {"questions": []}


def test_starters_empty_workspace_short_circuits_before_llm(api_client, monkeypatch):
    """An EMPTY workspace returns 200 `{questions: []}` WITHOUT any LLM call."""
    import graph.suggestions as suggestions_module

    calls = []

    class _Spy:
        def call_model(self, *a, **k):
            calls.append(a)
            return "[]"

    monkeypatch.setattr(suggestions_module, "LLMClient", _Spy)

    r = api_client.get("/suggestions/starters")
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"questions": []}
    assert calls == [], "empty workspace must short-circuit before any LLM call"


def test_starters_llm_error_still_200_empty(api_client, monkeypatch):
    """`LLMClient` raising -> 200 `{questions: []}` — never a 5xx."""
    import graph.suggestions as suggestions_module

    class _Boom:
        def call_model(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(suggestions_module, "LLMClient", _Boom)
    _make_dataset_row()

    r = api_client.get("/suggestions/starters")
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"questions": []}


def test_starters_catalog_is_metadata_only_no_file_reads(api_client, monkeypatch):
    """The catalog comes from `columns_json` + `context_facts` ONLY: the dataset
    rows have NO file on disk, and any pandas file-read call fails the test."""
    import graph.suggestions as suggestions_module

    def _no_read(*a, **k):  # pragma: no cover — must never run
        raise AssertionError("starters must not read data files/frames")

    monkeypatch.setattr(pd, "read_csv", _no_read)
    monkeypatch.setattr(pd, "read_parquet", _no_read)

    prompts: list[str] = []

    class _Capture:
        def call_model(self, prompt, *, system=None):
            prompts.append(prompt)
            return '["What is the total revenue by region?"]'

    monkeypatch.setattr(suggestions_module, "LLMClient", _Capture)

    _make_dataset_row(
        filename="revenue.csv",
        columns=["region", "revenue", "month"],
        context_facts=["monthly revenue per region", "12 months of data"],
    )

    r = api_client.get("/suggestions/starters")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["questions"] == ["What is the total revenue by region?"]

    # The single prompt carried the metadata catalog: filename, columns, facts.
    assert len(prompts) == 1
    prompt = prompts[0]
    assert "<node:suggest>" in prompt
    assert "revenue.csv" in prompt
    assert "region" in prompt and "revenue" in prompt and "month" in prompt
    assert "monthly revenue per region" in prompt


def test_generate_starter_questions_blank_catalog_is_noop(monkeypatch):
    """A blank catalog returns [] without constructing an LLM client."""
    import graph.suggestions as suggestions_module

    class _Boom:
        def __init__(self):
            raise AssertionError("no LLM client for a blank catalog")

    monkeypatch.setattr(suggestions_module, "LLMClient", _Boom)
    assert generate_starter_questions("") == []
    assert generate_starter_questions("   ") == []


def test_generate_starter_questions_caps_at_three(monkeypatch):
    import graph.suggestions as suggestions_module

    monkeypatch.setattr(
        suggestions_module, "LLMClient", _fake_llm('["q1", "q2", "q3", "q4", "q5"]')
    )
    assert generate_starter_questions("- a.csv: columns [x]") == ["q1", "q2", "q3"]


def test_generate_starter_questions_unparseable_reply_is_empty(monkeypatch):
    import graph.suggestions as suggestions_module

    monkeypatch.setattr(suggestions_module, "LLMClient", _fake_llm("no json here"))
    assert generate_starter_questions("- a.csv: columns [x]") == []


# --------------------------------------------------------------------------- #
# check_clarification (C26 + C37) — extended reply parsing
# --------------------------------------------------------------------------- #


def test_clarify_json_reply_yields_question_and_suggestions(monkeypatch):
    import graph.preflight as preflight_module

    reply = (
        '{"question": "Which metric do you mean?",'
        ' "suggestions": ["Average of price?", "Average of qty?", "Total revenue?"]}'
    )
    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm(reply))

    result = check_clarification("what is the average?", "schemas")
    assert isinstance(result, ClarificationResult)
    assert result.question == "Which metric do you mean?"
    assert result.suggestions == [
        "Average of price?",
        "Average of qty?",
        "Total revenue?",
    ]


def test_clarify_fenced_json_reply_is_parsed(monkeypatch):
    import graph.preflight as preflight_module

    reply = (
        "```json\n"
        '{"question": "Which column?", "suggestions": ["Average price?"]}\n'
        "```"
    )
    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm(reply))

    result = check_clarification("average?", "schemas")
    assert result == ClarificationResult("Which column?", ["Average price?"])


def test_clarify_more_than_three_suggestions_capped(monkeypatch):
    import graph.preflight as preflight_module

    reply = '{"question": "Which?", "suggestions": ["a", "b", "c", "d", "e"]}'
    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm(reply))

    result = check_clarification("q", "s")
    assert result.question == "Which?"
    assert result.suggestions == ["a", "b", "c"]


def test_clarify_missing_or_invalid_suggestions_become_empty(monkeypatch):
    import graph.preflight as preflight_module

    # Missing key.
    monkeypatch.setattr(
        preflight_module, "LLMClient", _fake_llm('{"question": "Which one?"}')
    )
    assert check_clarification("q", "s") == ClarificationResult("Which one?", [])

    # Invalid type (a string, not a list).
    monkeypatch.setattr(
        preflight_module,
        "LLMClient",
        _fake_llm('{"question": "Which one?", "suggestions": "not a list"}'),
    )
    assert check_clarification("q", "s") == ClarificationResult("Which one?", [])

    # Blank/empty entries are dropped.
    monkeypatch.setattr(
        preflight_module,
        "LLMClient",
        _fake_llm('{"question": "Which one?", "suggestions": ["", "  ", "real one"]}'),
    )
    assert check_clarification("q", "s") == ClarificationResult(
        "Which one?", ["real one"]
    )


def test_clarify_plain_text_reply_falls_back_to_whole_reply(monkeypatch):
    """Pre-C37 behavior preserved: a model that ignores the JSON grammar yields
    the whole trimmed reply as the question, with no candidates."""
    import graph.preflight as preflight_module

    monkeypatch.setattr(
        preflight_module,
        "LLMClient",
        _fake_llm("Which column do you want the average of?"),
    )
    result = check_clarification("what is the average?", "schemas")
    assert result == ClarificationResult(
        "Which column do you want the average of?", []
    )


def test_clarify_plain_text_wrapping_quotes_stripped(monkeypatch):
    """Wrapping backticks/quotes are stripped exactly as before C37 (backticks
    first, then quotes — the pre-existing strip order)."""
    import graph.preflight as preflight_module

    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm('`"Which column?"`'))
    result = check_clarification("q", "s")
    assert result == ClarificationResult("Which column?", [])


def test_clarify_json_with_empty_question_falls_back(monkeypatch):
    """A JSON reply whose `question` is empty is a parse FAILURE -> the whole
    trimmed reply becomes the clarifying question, candidates []."""
    import graph.preflight as preflight_module

    reply = '{"question": "", "suggestions": ["a"]}'
    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm(reply))
    result = check_clarification("q", "s")
    assert result == ClarificationResult(reply, [])


def test_clarify_bad_json_span_falls_back(monkeypatch):
    """An extractable-but-invalid `{...}` span falls back to the whole reply."""
    import graph.preflight as preflight_module

    reply = "{question: Which column?}"  # not valid JSON
    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm(reply))
    result = check_clarification("q", "s")
    assert result == ClarificationResult(reply, [])


def test_clarify_stub_proceed_and_empty_still_none(monkeypatch):
    """`proceed` (the stub branch) and an empty reply both still mean None."""
    import graph.preflight as preflight_module

    # The real stub provider path (autouse fixture forces it): "proceed" -> None.
    assert check_clarification("what is the average price?", "schemas") is None

    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm(""))
    assert check_clarification("q", "s") is None


# --------------------------------------------------------------------------- #
# POST /ask — the clarification payload carries suggested_questions
# --------------------------------------------------------------------------- #

_CSV = "product,price,qty\na,10,1\nb,20,2\nc,30,3\n"


def _upload_csv(client, name: str = "sample.csv"):
    files = {"file": (name, io.BytesIO(_CSV.encode()), "text/csv")}
    return client.post("/upload", files=files)


def test_ask_clarification_payload_carries_suggestions(api_client, monkeypatch):
    """A first-turn /ask whose pre-flight reply is the C37 JSON shape returns
    `type:"clarification"` with `suggested_questions` populated."""
    import graph.preflight as preflight_module

    reply = (
        '{"question": "Which metric do you mean by trend?",'
        ' "suggestions": ["Trend of price over qty?", "Trend of qty by product?"]}'
    )
    monkeypatch.setattr(preflight_module, "LLMClient", _fake_llm(reply))

    up = _upload_csv(api_client)
    assert up.status_code == 200, up.text

    r = api_client.post("/ask", json={"question": "show me the trend"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "clarification"
    assert data["status"] == "clarification"
    assert data["clarification_question"] == "Which metric do you mean by trend?"
    assert data["suggested_questions"] == [
        "Trend of price over qty?",
        "Trend of qty by product?",
    ]


def test_ask_clarification_fallback_parse_has_empty_suggestions(api_client, monkeypatch):
    """A plain-text pre-flight reply still clarifies (never blocked by the parse
    failure): the whole reply is the question, `suggested_questions` is []."""
    import graph.preflight as preflight_module

    monkeypatch.setattr(
        preflight_module,
        "LLMClient",
        _fake_llm("Which column should the trend be computed on?"),
    )

    up = _upload_csv(api_client)
    assert up.status_code == 200, up.text

    r = api_client.post("/ask", json={"question": "show me the trend"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "clarification"
    assert (
        data["clarification_question"]
        == "Which column should the trend be computed on?"
    )
    assert data["suggested_questions"] == []
