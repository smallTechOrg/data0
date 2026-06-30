import pytest


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    import config.settings as m
    m._settings = None
    yield
    m._settings = None


@pytest.fixture(autouse=True)
def _reset_node_registries():
    """Clear the process-global node registries between every test.

    `src/graph/nodes.py` keeps module-level dicts (`_dataframes`, `_derived_created`,
    `_session_cache`) that persist across tests in the same process. Left uncleared
    they leak state between tests (e.g. a stale session cache making notes-upload
    stub tests fail intermittently). Clearing in both setup and teardown makes
    `uv run pytest tests/unit/` deterministic regardless of test order.
    """
    import graph.nodes as nodes_module

    for registry in (
        nodes_module._dataframes,
        nodes_module._derived_created,
        nodes_module._session_cache,
    ):
        registry.clear()
    yield
    for registry in (
        nodes_module._dataframes,
        nodes_module._derived_created,
        nodes_module._session_cache,
    ):
        registry.clear()


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db.models import Base
    import db.session as session_module

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(session_module, "_engine", engine)
    monkeypatch.setattr(session_module, "_SessionLocal", factory)
    monkeypatch.setattr(session_module, "init_db", lambda: None)
    yield engine
    engine.dispose()


@pytest.fixture
def _require_llm_key():
    """Skip if no LLM provider key is set — Anthropic, Gemini, or OpenRouter."""
    from config.settings import get_settings
    s = get_settings()
    if not s.anthropic_api_key and not s.gemini_api_key and not s.openrouter_api_key:
        pytest.skip(
            "No LLM key set in .env (AGENT_ANTHROPIC_API_KEY, "
            "AGENT_GEMINI_API_KEY, or AGENT_OPENROUTER_API_KEY)"
        )


@pytest.fixture
def api_client(_isolated_db):
    """FastAPI test client with isolated DB."""
    from fastapi.testclient import TestClient
    from api import app
    with TestClient(app) as client:
        yield client
