"""Offline tests for C39 prompt-cache token accounting (Phase 14, slice-14a).

Zero env, no network. Covers, per spec/capabilities/prompt-cache-accounting.md:
- provider capture: a fake Gemini response whose `usage_metadata` carries
  `cached_content_token_count=N` yields `LLMResponse.tokens_cached == N`;
  absent/None -> 0; the stub (and the NamedTuple default the other providers
  rely on) reports 0
- state accumulation: `AgentState.tokens_cached` accumulates across iterations
  at the same sites as `tokens_input` (`plan_action` + `force_finalize`)
- persistence + payload exposure: the completed `query_runs` row carries
  `tokens_cached`, and `/ask`, `GET /runs/{run_id}`, `GET /sessions/{id}` turns
  and `GET /stats/daily` expose it (cached=0 AND cached>0 cases)
- the migration column contract: a pre-Phase-14 row (NULL `tokens_cached`)
  reads as 0 through every API surface, and the Alembic migration upgrades a
  pre-Phase-14 database cleanly with old rows reading 0
"""
import io
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# LLMResponse contract — tokens_cached defaults to 0 (anthropic/openrouter/stub
# construct it positionally with 3 args and stay honestly 0)
# ---------------------------------------------------------------------------


def test_llmresponse_defaults_tokens_cached_to_zero():
    from llm.providers.base import LLMResponse
    resp = LLMResponse("text", 100, 20)
    assert resp.tokens_cached == 0


def test_llmresponse_accepts_explicit_tokens_cached():
    from llm.providers.base import LLMResponse
    resp = LLMResponse("text", 100, 20, 74)
    assert (resp.tokens_input, resp.tokens_output, resp.tokens_cached) == (100, 20, 74)


def test_stub_provider_reports_zero_cached():
    from llm.providers.stub import StubProvider
    resp = StubProvider().complete("<node:plan>\nQuestion: q\n")
    assert resp.tokens_cached == 0


# ---------------------------------------------------------------------------
# Gemini provider capture — cached_content_token_count present / None / absent
# (fake client, no network — same harness as test_providers.py)
# ---------------------------------------------------------------------------


def _gemini_provider(outcomes):
    """GeminiProvider with a fake client — no real genai.Client, no network."""
    from llm.providers.gemini import GeminiProvider

    class _FakeModels:
        def __init__(self, scripted):
            self._scripted = list(scripted)

        def generate_content(self, *, model, contents, config):
            return self._scripted.pop(0)

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._client = SimpleNamespace(models=_FakeModels(outcomes))
    provider._model = "gemini-test"
    return provider


def test_gemini_parses_cached_content_token_count():
    response = SimpleNamespace(
        text="warm answer",
        usage_metadata=SimpleNamespace(
            prompt_token_count=16502,
            candidates_token_count=40,
            cached_content_token_count=12265,
        ),
    )
    resp = _gemini_provider([response]).complete("q")
    assert resp.tokens_input == 16502
    assert resp.tokens_output == 40
    assert resp.tokens_cached == 12265


def test_gemini_cached_none_reads_zero():
    """Cold call: Gemini returns cached_content_token_count=None -> 0."""
    response = SimpleNamespace(
        text="cold answer",
        usage_metadata=SimpleNamespace(
            prompt_token_count=16502,
            candidates_token_count=40,
            cached_content_token_count=None,
        ),
    )
    resp = _gemini_provider([response]).complete("q")
    assert resp.tokens_cached == 0


def test_gemini_cached_absent_reads_zero():
    """usage_metadata without the attribute at all -> 0 (getattr default)."""
    response = SimpleNamespace(
        text="answer",
        usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5,
        ),
    )
    resp = _gemini_provider([response]).complete("q")
    assert resp.tokens_cached == 0


def test_gemini_no_usage_metadata_reads_zero():
    response = SimpleNamespace(text="answer", usage_metadata=None)
    resp = _gemini_provider([response]).complete("q")
    assert (resp.tokens_input, resp.tokens_output, resp.tokens_cached) == (0, 0, 0)


# ---------------------------------------------------------------------------
# State accumulation — plan_action + force_finalize accumulate resp.tokens_cached
# at the same sites as tokens_input. NO chars/4 fallback for cached: a provider
# that reports nothing is honestly 0.
# ---------------------------------------------------------------------------


class _FakeLLMClient:
    """Stands in for graph.nodes.LLMClient — scripted LLMResponse per call."""

    _responses: list = []

    def __init__(self, *args, **kwargs):
        pass

    def complete(self, prompt, *, system=None):
        return type(self)._responses.pop(0)


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch nodes.LLMClient; tests load scripted responses onto the class."""
    import graph.nodes as nodes_module
    _FakeLLMClient._responses = []
    monkeypatch.setattr(nodes_module, "LLMClient", _FakeLLMClient)
    return _FakeLLMClient


def test_plan_action_accumulates_tokens_cached_across_iterations(fake_llm):
    from graph.nodes import plan_action
    from llm.providers.base import LLMResponse

    # Iteration 1 (cold): cached=0. Iteration 2 (warm): cached=120.
    fake_llm._responses = [
        LLMResponse("df.head()", 200, 10, 0),
        LLMResponse("FINAL ANSWER: done", 210, 12, 120),
    ]
    state = {
        "run_id": "run-cache-1",
        "question": "q",
        "iteration_count": 0,
        "max_iterations": 6,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_cached": 0,
    }
    state = plan_action(state)
    assert state["tokens_cached"] == 0
    assert state["tokens_input"] == 200

    state = plan_action(state)
    assert state["tokens_cached"] == 120
    assert state["tokens_input"] == 410
    # Invariant: 0 <= tokens_cached <= tokens_input.
    assert 0 <= state["tokens_cached"] <= state["tokens_input"]


def test_plan_action_no_estimation_fallback_for_cached(fake_llm):
    """tokens_input falls back to chars/4 when a provider reports 0 — but
    tokens_cached NEVER does: unreported cached stays honestly 0."""
    from graph.nodes import plan_action
    from llm.providers.base import LLMResponse

    fake_llm._responses = [LLMResponse("df.head()", 0, 0, 0)]
    state = {
        "run_id": "run-cache-2",
        "question": "q",
        "iteration_count": 0,
        "max_iterations": 6,
    }
    state = plan_action(state)
    assert state["tokens_input"] > 0  # chars/4 estimate kicked in
    assert state["tokens_cached"] == 0  # cached has NO estimate fallback


def test_force_finalize_accumulates_tokens_cached(fake_llm):
    from graph.nodes import force_finalize
    from llm.providers.base import LLMResponse

    fake_llm._responses = [LLMResponse("best-effort summary", 300, 30, 90)]
    state = {
        "run_id": "run-cache-3",
        "question": "q",
        "action_history": [{"action": "df.head()", "result": "ok", "is_error": False}],
        "tokens_input": 400,
        "tokens_output": 40,
        "tokens_cached": 60,
    }
    out = force_finalize(state)
    assert out["status"] == "completed"
    assert out["tokens_cached"] == 150  # 60 accumulated + 90 from the call
    assert out["tokens_input"] == 700


def test_force_finalize_llm_failure_keeps_accumulated_cached(monkeypatch):
    """The static-fallback path keeps the already-accumulated counts unchanged."""
    import graph.nodes as nodes_module

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def complete(self, prompt, *, system=None):
            raise RuntimeError("provider down")

    monkeypatch.setattr(nodes_module, "LLMClient", _Boom)
    state = {
        "run_id": "run-cache-4",
        "question": "q",
        "action_history": [],
        "tokens_input": 500,
        "tokens_output": 50,
        "tokens_cached": 70,
    }
    out = nodes_module.force_finalize(state)
    assert out["status"] == "completed"
    assert out["tokens_cached"] == 70
    assert out["tokens_input"] == 500


# ---------------------------------------------------------------------------
# Persistence + payload exposure (stub provider end-to-end: cached == 0)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_env(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    import config.settings as m
    m._settings = None


_CSV = "value,label\n10,a\n20,b\n30,c\n"


def _upload_csv(client, *, name="cache.csv", body=_CSV):
    files = {"file": (name, io.BytesIO(body.encode()), "text/csv")}
    r = client.post("/upload", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


def test_stub_run_persists_and_exposes_zero_cached(stub_env, api_client):
    """A stub run reports 0 cached everywhere — expected, never an error."""
    from db.models import QueryRunRow
    from db.session import create_db_session

    _upload_csv(api_client)
    ask = api_client.post("/ask", json={"question": "describe it"})
    assert ask.status_code == 200, ask.text
    data = ask.json()["data"]
    assert data["type"] == "answer"
    # /ask answer payload carries the field, payload-level (NOT in breakdown).
    assert data["tokens_cached"] == 0
    assert "tokens_cached" not in data["prompt_breakdown"]
    run_id = data["run_id"]

    # Row persisted with 0 (not NULL) — the runner writes it explicitly.
    with create_db_session() as s:
        row = s.get(QueryRunRow, run_id)
        assert row is not None
        assert row.tokens_cached == 0

    # GET /runs/{run_id}
    run = api_client.get(f"/runs/{run_id}").json()["data"]
    assert run["tokens_cached"] == 0

    # GET /sessions/{id} turn payload
    session_id = data["session_id"]
    detail = api_client.get(f"/sessions/{session_id}").json()["data"]
    assert detail["turns"][0]["tokens_cached"] == 0

    # GET /stats/daily — aggregate + last_tokens_cached, both 0.
    stats = api_client.get("/stats/daily").json()["data"]
    assert stats["tokens_cached"] == 0
    assert stats["last_tokens_cached"] == 0


def test_stats_daily_zero_cached_when_no_runs(api_client):
    stats = api_client.get("/stats/daily").json()["data"]
    assert stats["tokens_cached"] == 0
    assert stats["last_tokens_cached"] == 0


# ---------------------------------------------------------------------------
# Persistence + payload exposure (seeded rows: cached > 0 and NULL-old-row)
# ---------------------------------------------------------------------------


def _seed_run(*, session_id=None, tokens_input=1000, tokens_cached=812, **kw):
    from db.models import QueryRunRow
    from db.session import create_db_session

    with create_db_session() as s:
        row = QueryRunRow(
            dataset_id=None,
            session_id=session_id,
            question=kw.get("question", "seeded question"),
            answer=kw.get("answer", "seeded answer"),
            status=kw.get("status", "completed"),
            dataset_ids_json=[],
            iteration_count=kw.get("iteration_count", 2),
            tokens_input=tokens_input,
            tokens_output=kw.get("tokens_output", 50),
            tokens_cached=tokens_cached,
        )
        s.add(row)
        s.flush()
        return row.id


def test_run_payload_exposes_positive_cached(api_client):
    run_id = _seed_run(tokens_cached=812)
    run = api_client.get(f"/runs/{run_id}").json()["data"]
    assert run["tokens_cached"] == 812
    assert run["tokens_input"] == 1000


def test_session_turn_exposes_positive_cached(api_client):
    from db.models import ConversationSessionRow
    from db.session import create_db_session

    with create_db_session() as s:
        sess = ConversationSessionRow(dataset_id=None, dataset_ids_json=[], name=None)
        s.add(sess)
        s.flush()
        sid = sess.id
    _seed_run(session_id=sid, tokens_cached=812)

    detail = api_client.get(f"/sessions/{sid}").json()["data"]
    assert detail["turns"][0]["tokens_cached"] == 812


def test_stats_daily_aggregates_positive_cached(api_client):
    _seed_run(tokens_cached=500)
    _seed_run(tokens_cached=312)
    stats = api_client.get("/stats/daily").json()["data"]
    assert stats["tokens_cached"] == 812
    # last_tokens_cached mirrors the LATEST completed run.
    assert stats["last_tokens_cached"] in (312, 500)  # created same instant
    assert stats["tokens_input"] == 2000


def test_old_null_row_reads_zero_through_every_api(api_client):
    """Pre-Phase-14 row (tokens_cached NULL) reads 0 on runs/sessions/stats."""
    from db.models import ConversationSessionRow, QueryRunRow
    from db.session import create_db_session

    with create_db_session() as s:
        sess = ConversationSessionRow(dataset_id=None, dataset_ids_json=[], name=None)
        s.add(sess)
        s.flush()
        sid = sess.id
        row = QueryRunRow(
            dataset_id=None,
            session_id=sid,
            question="ancient question",
            answer="ancient answer",
            status="completed",
            dataset_ids_json=[],
            iteration_count=1,
            tokens_input=100,
            tokens_output=10,
            tokens_cached=None,  # explicit NULL, as a pre-migration row reads
        )
        s.add(row)
        s.flush()
        run_id = row.id

    assert api_client.get(f"/runs/{run_id}").json()["data"]["tokens_cached"] == 0
    detail = api_client.get(f"/sessions/{sid}").json()["data"]
    assert detail["turns"][0]["tokens_cached"] == 0
    stats = api_client.get("/stats/daily").json()["data"]
    assert stats["tokens_cached"] == 0
    assert stats["last_tokens_cached"] == 0


def test_clarification_row_carries_zero_cached(api_client):
    """Clarification short-circuit rows carry 0 like their other token fields."""
    from db.models import QueryRunRow
    from db.session import create_db_session

    run_id = _seed_run(status="clarification", tokens_input=0, tokens_cached=0,
                       answer="Which column did you mean?")
    with create_db_session() as s:
        row = s.get(QueryRunRow, run_id)
        assert row.tokens_cached == 0


# ---------------------------------------------------------------------------
# Domain read-shapes stay consistent with the row
# ---------------------------------------------------------------------------


def test_domain_query_run_carries_tokens_cached():
    from datetime import datetime, timezone
    from domain import QueryRun

    dto = QueryRun(
        id="r1",
        question="q",
        status="completed",
        iteration_count=1,
        tokens_input=100,
        tokens_output=10,
        tokens_cached=74,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert dto.tokens_cached == 74


def test_domain_session_turn_defaults_tokens_cached_zero():
    from domain import SessionTurn

    turn = SessionTurn(
        run_id="r1",
        question="q",
        answer_markdown="a",
        answer_html="<p>a</p>",
        iteration_count=1,
        tokens_input=100,
        tokens_output=10,
        status="completed",
        type="answer",
    )
    assert turn.tokens_cached == 0


# ---------------------------------------------------------------------------
# Alembic migration — upgrades a pre-Phase-14 DB cleanly; old rows read 0
# ---------------------------------------------------------------------------


def test_migration_adds_tokens_cached_and_old_rows_read_zero(tmp_path, monkeypatch):
    """Upgrade to the pre-Phase-14 head, seed a run row, upgrade to head, and
    confirm the seeded (old) row reads tokens_cached=0 — the SQLite ADD COLUMN
    server default. Runs against a throwaway file DB, not the real one."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    db_path = tmp_path / "migration.db"
    url = f"sqlite:///{db_path}"
    # env.py reads settings.database_url — point it at the throwaway DB.
    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    import config.settings as m
    m._settings = None

    repo_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))

    # Pre-Phase-14 schema (head before this slice's migration).
    command.upgrade(cfg, "d4e5f6a7b8c9")

    engine = create_engine(url)
    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(query_runs)"))]
        assert "tokens_cached" not in cols
        conn.execute(text(
            "INSERT INTO query_runs (id, question, status, iteration_count, "
            "tokens_input, tokens_output, fast_mode, created_at, updated_at) "
            "VALUES ('old-run', 'old q', 'completed', 1, 100, 10, 0, "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ))

    # Apply this slice's migration.
    command.upgrade(cfg, "head")

    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(query_runs)"))]
        assert "tokens_cached" in cols
        value = conn.execute(text(
            "SELECT tokens_cached FROM query_runs WHERE id='old-run'"
        )).scalar()
        # Pin the migration's server default hard: a NULL sneaking through the
        # backfill must FAIL here, not be laundered to 0 by an `or` fallback.
        assert value == 0

    # Downgrade drops the column cleanly.
    command.downgrade(cfg, "d4e5f6a7b8c9")
    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(query_runs)"))]
        assert "tokens_cached" not in cols
    engine.dispose()
