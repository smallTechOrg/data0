"""Phase 11 item 2 — exception-safe registry release in the runner.

The three run-scoped registries (`_dataframes`, `_loaded_ids`, `_derived_created`
in `src/graph/nodes.py`) used to be released only by the terminal graph nodes
(`finalize`/`force_finalize`/`handle_error`) plus the runner's post-invoke reads —
so an UNCAUGHT exception escaping any node propagated out of
`agentic_ai.invoke(...)` in `run_agent` and leaked that run's registries
(including the persisted eval namespace) for the process lifetime. `run_agent`
now wraps the invoke + the success-path registry reads in a `try/finally` whose
`finally` releases all three (idempotent `pop(run_id, None)` — the double release
on the success path is harmless).

Offline unit suite: stub LLM provider, isolated in-memory SQLite (conftest
`_isolated_db`), zero network. Setup mirrors tests/unit/test_graph_stub.py.
"""
from __future__ import annotations

import pandas as pd
import pytest

from db.models import DatasetRow
from db.session import create_db_session
from graph import nodes as nodes_module


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Make `LLMClient` use the offline stub provider for every test here."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    monkeypatch.delenv("AGENT_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_OPENROUTER_API_KEY", raising=False)
    # conftest's _reset_settings_singleton already resets the singleton each test.


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    """Point the nodes' uploads dir at a tmp dir so setup can load real files."""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: d)
    return d


def _make_dataset(uploads_dir, filename: str = "sales.csv") -> str:
    """Create a tiny CSV on disk + a `datasets` row; return the dataset id."""
    df = pd.DataFrame(
        {
            "product": ["a", "b", "c", "d"],
            "price": [10.0, 20.0, 30.0, 40.0],
            "qty": [1, 2, 3, 4],
        }
    )
    with create_db_session() as session:
        row = DatasetRow(
            filename=filename,
            file_path="",  # set below once we know the id
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


class _Boom(RuntimeError):
    """A deliberately unexpected node crash (not caught by any node)."""


def test_uncaught_node_exception_releases_all_three_registries(uploads_dir, monkeypatch):
    """A node raising an unexpected exception that propagates out of the graph
    invoke must still release `_dataframes`, `_loaded_ids`, AND `_derived_created`
    for that run — and the exception itself must still reach the caller."""
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    seen: dict[str, str] = {}

    def _exploding_eval(expr, namespace):
        # We are inside execute_action for the live run: capture its run_id and
        # verify all three registries are populated BEFORE the crash (so their
        # absence afterwards proves a release, not a never-populated registry).
        run_ids = list(nodes_module._dataframes)
        assert len(run_ids) == 1, f"expected exactly one live run bundle, got {run_ids}"
        run_id = run_ids[0]
        seen["run_id"] = run_id
        assert run_id in nodes_module._loaded_ids
        # Simulate a save_dataset registration earlier in the crashing run, so the
        # release of the THIRD registry is observable too.
        nodes_module._derived_created.setdefault(run_id, []).append("derived-x")
        raise _Boom("unexpected node crash")

    # execute_action calls eval_expression with no try around it — patching it is
    # an UNCAUGHT in-node crash (unlike an LLM error, which plan_action catches).
    monkeypatch.setattr(nodes_module, "eval_expression", _exploding_eval)

    # The exception still propagates to the caller exactly as before...
    with pytest.raises(_Boom):
        run_agent("Average price?", [dataset_id])

    # ...but the run's registries no longer leak for the process lifetime.
    run_id = seen["run_id"]
    assert run_id not in nodes_module._dataframes
    assert run_id not in nodes_module._loaded_ids
    assert run_id not in nodes_module._derived_created


def test_success_path_payload_unaffected_by_finally_release(uploads_dir):
    """On the success path the `finally` release is redundant (terminal nodes +
    the in-try reads already did the work) — the payload's `dataset_ids` /
    `derived_dataset_ids` must be read correctly BEFORE the release runs."""
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("Average price?", [dataset_id])

    assert result["status"] == "completed"
    assert result["answer"]
    # The stub's first action references `df` -> exactly this dataset was loaded,
    # and no save_dataset ran -> no derived ids. Neither is clobbered by the
    # now-redundant finally release.
    assert result["dataset_ids"] == [dataset_id]
    assert result["derived_dataset_ids"] == []

    # And all three registries are clean after the run, as always.
    run_id = result["run_id"]
    assert run_id not in nodes_module._dataframes
    assert run_id not in nodes_module._loaded_ids
    assert run_id not in nodes_module._derived_created
