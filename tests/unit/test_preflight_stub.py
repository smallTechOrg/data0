"""Offline unit tests for slice-3b pre-flight + suggestions + C27 session cache.

Zero env vars, no network, in-memory SQLite (via the autouse `_isolated_db`
fixture in conftest). The stub LLM provider drives every call: it branches only
on the injected node tags (`<node:clarify>` -> "proceed",
`<node:suggest>` -> "[]").

These tests verify the stub-mode contract and the deterministic cache behaviour;
the REAL-Gemini behaviour (a genuine clarifying question) is
covered by tests/integration/test_preflight_real.py.
"""
from __future__ import annotations

import pandas as pd
import pytest

from db.models import DatasetRow
from db.session import create_db_session
from graph import nodes as nodes_module
from graph.preflight import check_clarification
from graph.suggestions import generate_suggestions


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Make `LLMClient` use the offline stub provider for every test here."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    monkeypatch.delenv("AGENT_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_OPENROUTER_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _clear_session_cache():
    """C27 cache is module-level — clear it around each test for isolation."""
    nodes_module._session_cache.clear()
    yield
    nodes_module._session_cache.clear()


def _make_dataset(uploads_dir, filename: str = "sales.csv", columns=None) -> str:
    cols = columns or {
        "product": ["a", "b", "c", "d"],
        "price": [10.0, 20.0, 30.0, 40.0],
        "qty": [1, 2, 3, 4],
    }
    df = pd.DataFrame(cols)
    with create_db_session() as session:
        row = DatasetRow(
            filename=filename,
            file_path="",
            row_count=len(df),
            col_count=len(df.columns),
            columns_json=list(df.columns),
            content_hash="hash-" + filename,
            format="csv",
            origin="uploaded",
        )
        session.add(row)
        session.flush()
        dataset_id = row.id
        csv_path = uploads_dir / f"{dataset_id}.csv"
        df.to_csv(csv_path, index=False)
        row.file_path = str(csv_path)
    return dataset_id


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    """Point the nodes' uploads dir at a tmp dir so setup can load real files."""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: d)
    return d


# --------------------------------------------------------------------------- #
# check_clarification (C26) — stub returns "proceed" -> None
# --------------------------------------------------------------------------- #


def test_check_clarification_stub_proceeds():
    """The stub `<node:clarify>` reply is "proceed" -> no clarification (None)."""
    schemas = "- sales.csv (id abc): columns [product, price, qty]"
    result = check_clarification("What is the average price?", schemas)
    assert result is None


def test_check_clarification_fails_open(monkeypatch):
    """An LLM error returns None (fail-open) — never blocks the user."""
    import graph.preflight as preflight_module

    class _Boom:
        def call_model(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(preflight_module, "LLMClient", _Boom)
    assert check_clarification("anything", "schemas") is None


# --------------------------------------------------------------------------- #
# generate_suggestions — stub returns [] for <node:suggest>
# --------------------------------------------------------------------------- #


def test_generate_suggestions_stub_returns_empty():
    suggestions, t_in, t_out = generate_suggestions("What is the average?", "The average is 25.")
    assert suggestions == []
    # The call was still made, so token estimates are non-negative ints.
    assert isinstance(t_in, int) and t_in >= 0
    assert isinstance(t_out, int) and t_out >= 0


def test_generate_suggestions_blank_inputs_are_noops():
    assert generate_suggestions("", "answer") == ([], 0, 0)
    assert generate_suggestions("question", "") == ([], 0, 0)


def test_generate_suggestions_never_raises(monkeypatch):
    import graph.suggestions as suggestions_module

    class _Boom:
        def call_model(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(suggestions_module, "LLMClient", _Boom)
    assert generate_suggestions("q", "a") == ([], 0, 0)


# --------------------------------------------------------------------------- #
# C27 session DataFrame cache — reuse on a second lazy load in the same session
#
# Under agent-driven selection, `setup` is metadata-only (it reads NO frames), so
# the session cache is populated by the LAZY LOADER (`_session_load_frame`) the
# first time the agent references a dataset — not by `setup`. These tests exercise
# the loader directly (the exact function the eval namespace's loader delegates to).
# --------------------------------------------------------------------------- #


def test_session_cache_reuses_frame_on_second_load(uploads_dir, monkeypatch):
    """A second lazy load for the same (session_id, dataset_id) is a cache HIT —
    no re-read from disk, the cached entry is stable, and the returned frames are
    value-equal per-turn snapshots (never the same object; Phase 11 isolation)."""
    dataset_id = _make_dataset(uploads_dir)
    session_id = "session-xyz"

    # First reference: cache MISS -> loads from disk and stores under the session.
    frame1 = nodes_module._session_load_frame(session_id, dataset_id)
    assert session_id in nodes_module._session_cache
    cached = nodes_module._session_cache[session_id]["frames"][dataset_id]

    # Any further disk load would blow up loudly — a HIT is the only way through.
    def _no_reread(_dataset_id: str) -> pd.DataFrame:
        raise AssertionError("cache HIT expected — _load_dataframe must not be called")

    monkeypatch.setattr(nodes_module, "_load_dataframe", _no_reread)

    # Second reference (e.g. a later run of the same session): cache HIT.
    frame2 = nodes_module._session_load_frame(session_id, dataset_id)
    # The cached entry object is stable across both calls...
    assert nodes_module._session_cache[session_id]["frames"][dataset_id] is cached
    # ...and each turn gets a value-equal but distinct per-turn snapshot.
    pd.testing.assert_frame_equal(frame2, frame1)
    assert frame2 is not frame1


def test_session_cache_separate_sessions_do_not_share(uploads_dir):
    """Different session_ids get independent cache entries (different df objects)."""
    dataset_id = _make_dataset(uploads_dir)

    f1 = nodes_module._session_load_frame("s1", dataset_id)
    f2 = nodes_module._session_load_frame("s2", dataset_id)

    # Each session holds its OWN cached entry — distinct objects, no sharing.
    cached_s1 = nodes_module._session_cache["s1"]["frames"][dataset_id]
    cached_s2 = nodes_module._session_cache["s2"]["frames"][dataset_id]
    assert cached_s1 is not cached_s2
    assert f1 is not f2

    # Both sessions' returns carry the correct on-disk values.
    expected = pd.DataFrame(
        {
            "product": ["a", "b", "c", "d"],
            "price": [10.0, 20.0, 30.0, 40.0],
            "qty": [1, 2, 3, 4],
        }
    )
    pd.testing.assert_frame_equal(f1, expected)
    pd.testing.assert_frame_equal(f2, expected)


def test_single_turn_does_not_populate_session_cache(uploads_dir):
    """No session_id -> setup runs the per-run (metadata-only) path and never
    touches the session cache, which stays empty."""
    dataset_id = _make_dataset(uploads_dir)
    nodes_module.setup({"run_id": "r-single", "dataset_ids": [dataset_id], "session_id": None})
    assert nodes_module._session_cache == {}
    assert "r-single" in nodes_module._dataframes


def test_session_cache_lru_evicts_oldest(uploads_dir):
    """The session cache is bounded; overflowing it evicts the oldest session."""
    dataset_id = _make_dataset(uploads_dir)
    cap = nodes_module._SESSION_CACHE_MAX

    for i in range(cap + 2):
        nodes_module._session_load_frame(f"s{i}", dataset_id)

    assert len(nodes_module._session_cache) <= cap
    # The two oldest sessions were evicted.
    assert "s0" not in nodes_module._session_cache
    assert "s1" not in nodes_module._session_cache
    # The most-recent session is retained.
    assert f"s{cap + 1}" in nodes_module._session_cache
