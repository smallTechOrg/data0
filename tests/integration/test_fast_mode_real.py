"""Real-Gemini integration tests for C35 Fast Mode (slice-8a).

Requires `AGENT_GEMINI_API_KEY` in `.env` (auto-detect selects the real Gemini
provider). Drives `run_agent` directly (precise control over `run_clarification`
/ `fast_mode`, mirroring `tests/integration/test_preflight_real.py`) plus one
`POST /ask` round-trip via the `api_client` TestClient to confirm the API
contract (fast_mode echoed, model/provider unaffected).

Asserts REAL, measurable behavior differences driven by the toggle:
- a Fast Mode run makes ZERO non-iteration LLM roundtrips (real calls counted
  via a spy == iteration_count exactly: no suggestion call, no clarification
  call), while an equivalent non-Fast-Mode run pays its suggestion roundtrip
  (calls == iteration_count + 1) — each run checked against its own exact
  arithmetic, never raced head-to-head (iteration counts are model luck)
- a Fast Mode run's iteration_count never exceeds 5
- a question that would normally trigger a clarifying question instead proceeds
  straight to an answer (type:"answer") under Fast Mode
- the model/provider is identical between a Fast Mode and non-Fast-Mode run
"""
from __future__ import annotations

import io

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


def _make_dataset(uploads_dir, filename: str, df: pd.DataFrame) -> str:
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
        )
        session.add(row)
        session.flush()
        dataset_id = row.id
        csv_path = uploads_dir / f"{dataset_id}.csv"
        df.to_csv(csv_path, index=False)
        df.to_parquet(uploads_dir / f"{dataset_id}.parquet")
        row.file_path = str(csv_path)
    return dataset_id


def _ambiguous_financials_df() -> pd.DataFrame:
    """Multiple numeric columns, no column named -> "What is the average?" is
    genuinely ambiguous, the same shape used by test_preflight_real.py."""
    return pd.DataFrame(
        {
            "revenue": [100.0, 200.0, 300.0, 400.0],
            "cost": [40.0, 80.0, 120.0, 160.0],
            "units": [5, 10, 15, 20],
        }
    )


# --------------------------------------------------------------------------- #
# Clarification bypass: an ambiguous question that a normal run WOULD clarify on
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("_require_llm_key")
def test_fast_mode_skips_clarification_normal_mode_would_ask_real_gemini(uploads_dir):
    """The SAME genuinely ambiguous question ("What is the average?" over a frame
    with 3 numeric columns, no column named): a normal first-turn run may ask a
    clarifying question; fast_mode=True on the identical question/dataset shape
    must NEVER clarify — it always proceeds straight to type:"answer"."""
    df = _ambiguous_financials_df()

    # --- Normal mode run: confirm the question IS ambiguous enough to clarify --
    normal_dataset_id = _make_dataset(uploads_dir, "financials_normal.csv", df)
    normal_result = run_agent(
        "What is the average?",
        [normal_dataset_id],
        run_clarification=True,
        skip_clarification=False,
        fast_mode=False,
    )
    print(f"\n[normal] type={normal_result['type']}")
    assert normal_result["type"] == "clarification", (
        "test fixture assumption failed: this question must be ambiguous enough "
        f"for the real model to clarify under normal mode; got {normal_result.get('type')} "
        "(if the model's clarification judgment has drifted, pick a more ambiguous "
        "fixture rather than loosening this assertion)"
    )

    # --- Fast Mode run: identical question/dataset shape, fresh dataset ------
    fast_dataset_id = _make_dataset(uploads_dir, "financials_fast.csv", df)
    fast_result = run_agent(
        "What is the average?",
        [fast_dataset_id],
        run_clarification=True,
        skip_clarification=False,
        fast_mode=True,
    )

    assert fast_result["type"] == "answer", (
        f"fast_mode=True must proceed straight to an answer even on a question a "
        f"normal run would clarify on; got {fast_result.get('type')}"
    )
    assert fast_result["status"] == "completed"
    assert fast_result["iteration_count"] <= 5, (
        f"fast_mode iteration_count must never exceed 5, got "
        f"{fast_result['iteration_count']}"
    )
    assert fast_result["suggested_questions"] == []

    answer = fast_result["answer"]
    assert answer and answer.strip(), "fast_mode must still produce a real answer"
    assert "[stub]" not in answer, "got a stub answer — real provider not used"

    print(f"[fast] type={fast_result['type']} iteration_count={fast_result['iteration_count']}")


# --------------------------------------------------------------------------- #
# Non-iteration roundtrips eliminated: count REAL LLM calls per run and check
# each run against its own exact arithmetic. A strict fast-vs-normal roundtrip
# comparison is racy under real-LLM nondeterminism (the normal run can get
# lucky on iterations while the fast run self-corrects an execution error —
# observed live 2026-07-07), so the guaranteed savings are asserted instead:
# Fast Mode's total calls == its iteration count (zero suggestion/clarification
# overhead), normal's == iteration count + 1 (the suggestion roundtrip).
# --------------------------------------------------------------------------- #


@pytest.fixture
def _count_llm_calls(monkeypatch):
    """Spy on BOTH LLMClient entry points, counting real provider roundtrips.

    `LLMClient.call_model` delegates to the provider directly (not to
    `LLMClient.complete`), so wrapping both never double-counts."""
    from llm.client import LLMClient

    counts = {"n": 0}
    orig_complete = LLMClient.complete
    orig_call_model = LLMClient.call_model

    def counting_complete(self, prompt, *, system=None):
        counts["n"] += 1
        return orig_complete(self, prompt, system=system)

    def counting_call_model(self, prompt, *, system=None):
        counts["n"] += 1
        return orig_call_model(self, prompt, system=system)

    monkeypatch.setattr(LLMClient, "complete", counting_complete)
    monkeypatch.setattr(LLMClient, "call_model", counting_call_model)
    return counts


@pytest.mark.usefixtures("_require_llm_key")
def test_fast_mode_eliminates_non_iteration_roundtrips_real_gemini(
    uploads_dir, _count_llm_calls
):
    """Ask the SAME unambiguous multi-step question twice (fresh dataset each
    time), both with clarification skipped, counting REAL LLM calls per run.

    Per-run call arithmetic (normally-completed run, clarification skipped):
    plan_action makes exactly one call per iteration and `finalize` makes none
    (only `force_finalize` would add a synthesis call — excluded by asserting
    `is_best_effort` is False). So:
    - normal run: calls == iteration_count + 1  (the always-run suggestion call)
    - fast run:   calls == iteration_count      (zero non-iteration overhead)
    Each run is checked against its own arithmetic — iteration counts are model
    luck and are never compared across runs."""
    df = pd.DataFrame(
        {
            "region": ["north", "south", "east", "west", "north", "south"],
            "product": ["a", "b", "a", "b", "b", "a"],
            "revenue": [100.0, 200.0, 150.0, 250.0, 180.0, 220.0],
        }
    )
    question = (
        "Break down total revenue by region AND by product, then tell me which "
        "single region+product combination has the highest revenue."
    )

    normal_dataset_id = _make_dataset(uploads_dir, "sales_normal.csv", df)
    normal_result = run_agent(
        question,
        [normal_dataset_id],
        run_clarification=False,
        skip_clarification=True,
        fast_mode=False,
    )
    normal_calls = _count_llm_calls["n"]
    assert normal_result["type"] == "answer"
    assert normal_result["is_best_effort"] is False, (
        "fixture question unexpectedly force-finalized — the call arithmetic "
        "below assumes a normal completion"
    )
    print(f"\n[normal] iteration_count={normal_result['iteration_count']} "
          f"llm_calls={normal_calls} suggestions={normal_result['suggested_questions']}")
    assert normal_calls == normal_result["iteration_count"] + 1, (
        f"normal mode must pay exactly one non-iteration roundtrip (the "
        f"suggestion call); calls={normal_calls} "
        f"iterations={normal_result['iteration_count']}"
    )

    fast_dataset_id = _make_dataset(uploads_dir, "sales_fast.csv", df)
    fast_result = run_agent(
        question,
        [fast_dataset_id],
        run_clarification=False,
        skip_clarification=True,
        fast_mode=True,
    )
    fast_calls = _count_llm_calls["n"] - normal_calls
    assert fast_result["type"] == "answer"
    assert fast_result["is_best_effort"] is False, (
        "fixture question unexpectedly force-finalized — the call arithmetic "
        "below assumes a normal completion"
    )
    assert fast_result["suggested_questions"] == []
    print(f"[fast] iteration_count={fast_result['iteration_count']} "
          f"llm_calls={fast_calls}")

    assert fast_result["iteration_count"] <= 5, (
        f"fast_mode iteration_count must never exceed 5, got "
        f"{fast_result['iteration_count']}"
    )
    assert fast_calls == fast_result["iteration_count"], (
        f"fast_mode must make ZERO non-iteration LLM roundtrips (no suggestion "
        f"call, no clarification call); calls={fast_calls} "
        f"iterations={fast_result['iteration_count']}"
    )

    answer = fast_result["answer"]
    assert answer and answer.strip(), "fast_mode must still produce a real answer"
    assert "[stub]" not in answer, "got a stub answer — real provider not used"


# --------------------------------------------------------------------------- #
# Model/provider identity: fast_mode never affects model/provider selection
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("_require_llm_key")
def test_fast_mode_does_not_change_model_or_provider(api_client, uploads_dir):
    """A Fast Mode request and a non-Fast-Mode request in the SAME settings
    configuration resolve to the IDENTICAL model/provider (via GET /health,
    which reads the live LLMClient resolution — unaffected by any request body)."""
    health_before = api_client.get("/health")
    assert health_before.status_code == 200
    provider_before = health_before.json()["data"]["provider"]
    model_before = health_before.json()["data"]["model"]
    assert provider_before != "stub", "expected a real provider for this test"

    # Upload via the API so the /ask round-trip is realistic end-to-end.
    csv = "value\n10\n20\n30\n40\n50\n"
    up = api_client.post(
        "/upload", files={"file": ("numbers.csv", io.BytesIO(csv.encode()), "text/csv")}
    )
    assert up.status_code == 200, up.text

    r_fast = api_client.post(
        "/ask",
        json={
            "question": "What is the average of the value column?",
            "skip_clarification": True,
            "fast_mode": True,
        },
    )
    assert r_fast.status_code == 200, r_fast.text
    d_fast = r_fast.json()["data"]
    assert d_fast["type"] == "answer"
    assert d_fast["fast_mode"] is True
    assert d_fast["iteration_count"] <= 5

    r_normal = api_client.post(
        "/ask",
        json={
            "question": "What is the average of the value column?",
            "skip_clarification": True,
            "fast_mode": False,
        },
    )
    assert r_normal.status_code == 200, r_normal.text
    d_normal = r_normal.json()["data"]
    assert d_normal["type"] == "answer"
    assert d_normal["fast_mode"] is False

    health_after = api_client.get("/health")
    provider_after = health_after.json()["data"]["provider"]
    model_after = health_after.json()["data"]["model"]

    assert provider_after == provider_before, "fast_mode must not change provider"
    assert model_after == model_before, "fast_mode must not change model"


# --------------------------------------------------------------------------- #
# Live-server-adjacent smoke: a real /ask round-trip with fast_mode:true
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("_require_llm_key")
def test_fast_mode_ask_smoke_real_gemini(api_client):
    """A single real fast_mode:true round-trip via the API returns real AI
    output with iteration_count <= 5 (mirrors the live-server smoke in the gate)."""
    csv = "product,price,qty\na,10,1\nb,20,2\nc,30,3\nd,40,4\n"
    up = api_client.post(
        "/upload", files={"file": ("sales.csv", io.BytesIO(csv.encode()), "text/csv")}
    )
    assert up.status_code == 200, up.text

    r = api_client.post(
        "/ask",
        json={
            "question": "What is the total revenue (price * qty summed)?",
            "skip_clarification": True,
            "fast_mode": True,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "answer"
    assert data["status"] == "completed"
    assert data["fast_mode"] is True
    assert data["iteration_count"] <= 5
    answer = data["answer_markdown"]
    assert answer and answer.strip()
    assert "[stub]" not in answer
