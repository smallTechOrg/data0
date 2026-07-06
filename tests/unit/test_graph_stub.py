"""Offline unit tests for the ReAct graph (slice-2b).

Zero env vars, no network, in-memory SQLite (via the autouse `_isolated_db`
fixture in conftest). The stub LLM provider drives the loop: it branches only on
the injected `<node:plan>` / `<node:finalize>` tags. The combined unit suite is
run by the orchestrator after slice-2a (the stub provider + `client.py` stub
branch) lands; these tests pass once `LLMClient` honors `AGENT_LLM_PROVIDER=stub`.
"""
from __future__ import annotations

import pandas as pd
import pytest

from db.models import DatasetRow
from db.session import create_db_session
from graph import nodes as nodes_module
from graph.edges import after_execute, after_plan, after_setup


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Make `LLMClient` use the offline stub provider for every test here."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    monkeypatch.delenv("AGENT_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_OPENROUTER_API_KEY", raising=False)
    # conftest's _reset_settings_singleton already resets the singleton each test.


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


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    """Point the nodes' uploads dir at a tmp dir so setup can load real files."""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: d)
    return d


# --------------------------------------------------------------------------- #
# Compilation
# --------------------------------------------------------------------------- #


def test_graph_compiles():
    from graph.agent import agentic_ai

    assert agentic_ai is not None


def test_runner_signature_importable():
    from graph.runner import run_agent  # noqa: F401

    assert callable(run_agent)


# --------------------------------------------------------------------------- #
# Full run via run_agent (happy path)
# --------------------------------------------------------------------------- #


def test_run_agent_completes_with_answer(uploads_dir):
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("What is the average price?", [dataset_id])

    assert result["status"] == "completed"
    assert result["answer"] and isinstance(result["answer"], str)
    assert len(result["answer"]) > 0
    # The stub runs one describe action then a FINAL ANSWER, so at least one step.
    assert len(result["action_history"]) >= 1
    assert result["iteration_count"] >= 1
    assert result["dataset_ids"] == [dataset_id]
    # Tokens are estimated for the stub provider (len//4 heuristic).
    assert result["tokens_input"] > 0
    assert result["tokens_output"] > 0


def test_run_agent_return_dict_keys(uploads_dir):
    """The exact keys slice-2c's /ask route consumes."""
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("Describe the data.", [dataset_id])

    expected_keys = {
        "run_id",
        "status",
        "answer",
        "iteration_count",
        "tokens_input",
        "tokens_output",
        "action_history",
        "charts",
        "dataset_ids",
        "is_best_effort",
        "selector_reasoning",
    }
    assert expected_keys.issubset(set(result.keys()))


def test_run_agent_persists_query_run(uploads_dir):
    from db.models import QueryRunRow
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("Average price?", [dataset_id])

    with create_db_session() as session:
        row = session.get(QueryRunRow, result["run_id"])
        assert row is not None
        assert row.status == "completed"
        assert row.answer
        assert row.question == "Average price?"
        assert row.dataset_ids_json == [dataset_id]
        assert row.action_history is not None


def test_run_agent_records_only_loaded_datasets(uploads_dir):
    """Agent-driven selection (C19) + used-tracking: with THREE datasets in the
    catalog, the stub's first action is `df.describe()` — which references only `df`
    (the first catalog dataset). The run must record ONLY that dataset in
    `dataset_ids_json` (not all three), so "Datasets used" is accurate and the C15
    cascade-delete of one dataset can't wipe conversations that never touched it."""
    from db.models import QueryRunRow
    from graph.runner import run_agent

    first = _make_dataset(uploads_dir, filename="sales.csv")
    second = _make_dataset(uploads_dir, filename="employees.csv")
    third = _make_dataset(uploads_dir, filename="inventory.csv")

    result = run_agent("Summarise the data.", [first, second, third])

    # The stub loads only `df` (the first catalog dataset) -> only it is recorded.
    assert result["dataset_ids"] == [first]
    assert second not in result["dataset_ids"]
    assert third not in result["dataset_ids"]

    with create_db_session() as session:
        row = session.get(QueryRunRow, result["run_id"])
        assert row.dataset_ids_json == [first]


def test_first_action_executes_describe(uploads_dir):
    """Stub's first <node:plan> reply is `df.describe().to_string()` — it must run
    cleanly against the real loaded DataFrame and be recorded as a non-error step."""
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("Summarise.", [dataset_id])

    first = result["action_history"][0]
    assert first["action"] == "df.describe().to_string()"
    assert first["is_error"] is False
    assert "price" in first["result"]  # describe output mentions the numeric columns


def test_run_releases_dataframe_registry(uploads_dir):
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("Average price?", [dataset_id])

    # finalize/force_finalize/handle_error all release the run-scoped frame.
    assert result["run_id"] not in nodes_module._dataframes


def test_ordinary_variable_persists_across_dependent_steps(uploads_dir, monkeypatch):
    """Regression for the rebuilt-namespace bug: an ordinary variable a model
    assigns in one step (e.g. `tmp = df1.head(2)`) must still be bound in the
    NEXT step of the same run — the persisted `bundle["namespace"]` (nodes.py's
    `execute_action`) carries ordinary locals forward exactly like successive
    cells in one Jupyter kernel, not just `save_dataset`'d frames.

    The stock `StubProvider` always finalizes after exactly one action, so it
    can never exercise two dependent steps — this test scripts its own
    sequence of planner replies via a fake `LLMClient` to force two REAL,
    dependent ReAct iterations.
    """
    from graph.runner import run_agent
    from llm.providers.base import LLMResponse

    dataset_id = _make_dataset(uploads_dir)

    # Step 1 defines `tmp`; step 2 REFERENCES that same name (with no re-load in
    # between) — this only works if `tmp` is still bound from step 1.
    scripted_replies = iter(
        [
            "tmp = df1.head(2)",
            "tmp['price'].sum()",
            "FINAL ANSWER: [stub] done",
        ]
    )

    class _ScriptedLLMClient:
        def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
            text = next(scripted_replies)
            return LLMResponse(text, max(1, len(text) // 4), max(1, len(text) // 4))

    monkeypatch.setattr(nodes_module, "LLMClient", _ScriptedLLMClient)

    result = run_agent("What is the sum of price for the first two rows?", [dataset_id])

    assert result["status"] == "completed"
    steps = result["action_history"]
    assert len(steps) >= 2
    step1, step2 = steps[0], steps[1]
    assert step1["action"] == "tmp = df1.head(2)"
    assert step1["is_error"] is False
    # The bug: step 2 referencing `tmp` would raise a NameError (the namespace
    # was rebuilt fresh each iteration, so `tmp` never carried over).
    assert step2["action"] == "tmp['price'].sum()"
    assert step2["is_error"] is False, f"expected tmp to persist, got: {step2['result']}"
    assert "NameError" not in step2["result"]
    # tmp = df1.head(2) -> price column [10.0, 20.0] -> sum 30.0
    assert "30" in step2["result"]

    # The release-on-completion invariant must still hold with the persisted
    # namespace living inside the same released bundle.
    assert result["run_id"] not in nodes_module._dataframes


# --------------------------------------------------------------------------- #
# Error path: a referenced dataset whose file is missing surfaces as a STEP error
# --------------------------------------------------------------------------- #


def test_missing_dataset_file_surfaces_as_step_error(uploads_dir):
    """Under agent-driven lazy loading, `setup` is metadata-only, so a missing CSV
    no longer hard-fails the run at setup. It surfaces as an execution error the
    first time the agent references the frame; the agent then wraps up best-effort
    (the run completes rather than routing to handle_error)."""
    from graph.runner import run_agent

    # Insert a datasets row but DO NOT write the CSV -> the lazy load fails when the
    # agent first references the frame (setup, being metadata-only, still succeeds).
    with create_db_session() as session:
        row = DatasetRow(
            filename="ghost.csv",
            file_path="",
            row_count=0,
            col_count=0,
            columns_json=[],
            content_hash="ghost",
            format="csv",
            origin="uploaded",
        )
        session.add(row)
        session.flush()
        dataset_id = row.id

    result = run_agent("anything", [dataset_id])

    # The run does NOT hard-fail (metadata-only setup succeeded); it completes.
    assert result["status"] == "completed"
    # ...but the missing-file load was recorded as an execution error step.
    steps = result.get("action_history", [])
    assert any(step.get("is_error") for step in steps), (
        f"expected the missing-file load to surface as an error step; got {steps}"
    )


def test_unknown_dataset_id_fails(uploads_dir):
    from graph.runner import run_agent

    result = run_agent("anything", ["does-not-exist"])
    assert result["status"] == "failed"


# --------------------------------------------------------------------------- #
# Edge routers (unit-level, no LLM)
# --------------------------------------------------------------------------- #


def test_after_setup_routes_on_error():
    assert after_setup({"error": "boom"}) == "handle_error"
    assert after_setup({}) == "plan_action"


def test_after_plan_final_answer_routes_to_finalize():
    assert after_plan({"llm_response": "FINAL ANSWER: 42"}) == "finalize"
    assert after_plan({"llm_response": "...some preamble... final answer: x"}) == "finalize"
    assert after_plan({"llm_response": "df['price'].mean()"}) == "execute_action"
    assert after_plan({"error": "boom"}) == "handle_error"


def test_after_execute_max_iter_routes_to_force_finalize():
    state = {"iteration_count": 6, "max_iterations": 6, "action_history": []}
    assert after_execute(state) == "force_finalize"


def test_after_execute_consecutive_errors_routes_to_force_finalize():
    history = [{"is_error": True}, {"is_error": True}, {"is_error": True}]
    state = {"iteration_count": 2, "max_iterations": 6, "action_history": history}
    assert after_execute(state) == "force_finalize"


def test_after_execute_recoverable_error_loops_to_plan():
    history = [{"is_error": False}, {"is_error": True}]
    state = {"iteration_count": 2, "max_iterations": 6, "action_history": history}
    assert after_execute(state) == "plan_action"


def test_after_execute_fatal_error_routes_to_handle_error():
    assert after_execute({"error": "fatal", "action_history": []}) == "handle_error"


# --------------------------------------------------------------------------- #
# force_finalize: best-effort completion on max-iter
# --------------------------------------------------------------------------- #


def test_force_finalize_on_max_iter_completes(uploads_dir):
    """With max_iterations=1 the loop force-finalizes after one action."""
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("Average price?", [dataset_id], max_iterations=1)

    assert result["status"] == "completed"
    assert result["answer"]
    assert result["is_best_effort"] is True


# --------------------------------------------------------------------------- #
# Sandbox helpers (no LLM, no DB)
# --------------------------------------------------------------------------- #


def test_sandbox_eval_expression_ok():
    from graph.sandbox import build_namespace, eval_expression

    df = pd.DataFrame({"x": [1, 2, 3]})
    ns = build_namespace([df], ["nums.csv"])
    result_str, charts, is_error, error_str = eval_expression("df['x'].sum()", ns)
    assert is_error is False
    assert error_str is None
    assert "6" in result_str
    assert charts == []


def test_sandbox_eval_expression_error_is_recoverable():
    from graph.sandbox import build_namespace, eval_expression

    df = pd.DataFrame({"x": [1, 2, 3]})
    ns = build_namespace([df])
    result_str, charts, is_error, error_str = eval_expression("df['missing'].sum()", ns)
    assert is_error is True
    assert error_str  # non-empty error string fed back to the model


def test_sandbox_namespace_aliases():
    from graph.sandbox import build_namespace

    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"b": [2]})
    ns = build_namespace([df1, df2], ["sales.csv", "orders.csv"])
    assert ns["df"] is df1
    assert ns["df1"] is df1
    assert ns["df2"] is df2
    assert ns["sales"] is df1
    assert ns["orders"] is df2
    # Libraries present (Plotly px/go removed — charts go through echart()).
    for lib in ("pd", "np", "plt", "sns", "scipy", "stats", "sklearn", "sm"):
        assert lib in ns
    assert callable(ns["save_dataset"])
    assert callable(ns["echart"])
    assert "px" not in ns and "go" not in ns


def test_sandbox_captures_echart_chart_via_accumulator():
    """An echart(...) call registers exactly one ECharts option whose JSON has a
    series key. eval_expression itself returns no charts — the node owns the
    json.dumps serialisation by reading the accumulator."""
    import json

    from graph.sandbox import build_namespace, eval_expression, make_echart

    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    ns = build_namespace([df])
    captured = []
    ns["echart"] = make_echart(on_chart=captured.append)

    result_str, charts, is_error, error_str = eval_expression(
        "echart('scatter', df, x='x', y='y', title='xy')", ns
    )
    assert is_error is False
    assert charts == []  # not captured here — the node reads the accumulator
    assert len(captured) == 1
    parsed = json.loads(json.dumps(captured[0]))
    assert "series" in parsed


def test_save_dataset_stub_returns_string_without_writing():
    from graph.sandbox import save_dataset

    df = pd.DataFrame({"x": [1, 2]})
    msg = save_dataset(df, "derived_thing", "a desc")
    assert isinstance(msg, str)
    assert "derived_thing" in msg


# --------------------------------------------------------------------------- #
# C31 — compressed facts are injected into the plan prompt (not the raw notes)
# --------------------------------------------------------------------------- #


def _set_context(dataset_id: str, *, context=None, facts=None) -> None:
    """Set a dataset's raw `context` and/or compressed `context_facts`."""
    with create_db_session() as session:
        row = session.get(DatasetRow, dataset_id)
        if context is not None:
            row.context = context
        if facts is not None:
            row.context_facts = facts


def test_setup_injects_compressed_facts_not_raw_notes(uploads_dir):
    """C31: a dataset with compressed facts contributes those FACTS to its catalog
    line — never the longer raw notes. `setup` reads ONLY the cached `context_facts`
    and never compresses on demand (agent-driven selection: the catalog spans every
    dataset, so a synchronous compress-per-dataset would be a first-turn storm)."""
    dataset_id = _make_dataset(uploads_dir)
    raw = "This is a long-winded paragraph of raw notes that should be compressed away."
    _set_context(dataset_id, context=raw, facts=["fiscal year starts in April", "revenue in USD"])

    result = nodes_module.setup({"run_id": "r-facts", "dataset_ids": [dataset_id]})
    ctx = result["dataset_context"]

    assert "fiscal year starts in April; revenue in USD" in ctx  # facts injected
    assert raw not in ctx  # raw notes NOT injected


def test_setup_reads_no_frames(uploads_dir, monkeypatch):
    """C19 criterion #2: `setup` builds the catalog from metadata ONLY — it must
    never call `_load_dataframe` (no Parquet/CSV reads during setup).

    The metadata (filename, columns_json) comes exclusively from the DB rows that
    `_make_dataset` populates. The returned `dataset_context` must be non-empty to
    confirm the catalog was built successfully without touching any data files.
    """
    first = _make_dataset(uploads_dir, filename="alpha.csv")
    second = _make_dataset(uploads_dir, filename="beta.csv")

    load_calls: list[str] = []

    def _fake_load(dataset_id: str) -> pd.DataFrame:
        load_calls.append(dataset_id)
        return pd.DataFrame()  # never reached in a correct setup

    monkeypatch.setattr(nodes_module, "_load_dataframe", _fake_load)

    result = nodes_module.setup({"run_id": "r-no-frames", "dataset_ids": [first, second]})

    # setup must NEVER read a frame — the catalog is metadata-only.
    assert load_calls == [], (
        f"setup called _load_dataframe for: {load_calls}; expected zero frame reads"
    )
    # The catalog itself must be non-empty (metadata was read from DB, not frames).
    ctx = result.get("dataset_context", "")
    assert ctx, "setup returned an empty dataset_context — catalog build failed"


def test_catalog_block_lean_counts_and_previews():
    """C33 token economics: a WIDE table is compressed to its column COUNT + a preview
    of only the first `_CATALOG_COLUMN_PREVIEW` names + a `(+K more)` pointer, NOT the
    full column list — the agent pulls the rest on demand (`df{n}.columns`). The
    compressed form is adopted precisely because it is SHORTER than listing every
    column (Pareto: never worse than a plain schema). Compressed notes still append."""
    n = nodes_module._CATALOG_COLUMN_PREVIEW
    # Realistically-named wide table: enough columns that the count+preview form is
    # decisively shorter than the full listing (so compression is adopted).
    wide_cols = [f"feature_{i:02d}_value" for i in range(n + 18)]
    entry = {
        "id": "d1",
        "filename": "wide.csv",
        "alias": "wide",
        "columns": wide_cols,
        "notes": "one compact fact",
    }
    line = nodes_module._catalog_block(0, entry)
    schema_line = line.splitlines()[0]  # the schema line, before the appended notes

    assert "`df1` (alias `wide`)" in line  # how to reference it
    assert "wide.csv" in line
    assert f"{len(wide_cols)} cols:" in line  # the COUNT, not just the names
    # Only the first `n` names are previewed; the tail is summarised, not listed.
    assert wide_cols[0] in line and wide_cols[n - 1] in line
    assert wide_cols[n] not in line  # the (n+1)th column is NOT spelled out
    assert "(+18 more" in line and "`df1.columns`" in line  # on-demand pointer
    # Pareto guarantee: the compressed schema line is strictly shorter than listing
    # every column would have been.
    full_listing = f"- `df1` (alias `wide`) — wide.csv: {', '.join(wide_cols)}"
    assert len(schema_line) < len(full_listing)
    assert "notes: one compact fact" in line


def test_catalog_block_narrow_table_lists_all_columns_no_more():
    """C33: a table no wider than the preview lists ALL its columns with NO count/
    preview overhead — byte-for-byte the pre-C33 line — so the lean catalog is NEVER
    larger than a plain column listing (the compression only kicks in on wide tables).
    """
    entry = {"filename": "sales.csv", "alias": "sales", "columns": ["product", "price", "qty"]}
    line = nodes_module._catalog_block(0, entry)

    assert "sales.csv: product, price, qty" in line  # all columns, plain listing
    assert "more" not in line  # no (+K more) tail
    assert "cols:" not in line  # no "N cols:" prefix — zero overhead vs pre-C33


# --------------------------------------------------------------------------- #
# D2 — invalidate_dataset_cache removes dataset from ALL session entries (C27)
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=False)
def _clear_session_cache():
    """Ensure the session cache is empty before and after each D2 test."""
    nodes_module._session_cache.clear()
    yield
    nodes_module._session_cache.clear()


def test_invalidate_dataset_cache_removes_from_all_sessions(_clear_session_cache):
    """After invalidate_dataset_cache(dataset_id), that id is absent in every session."""
    dataset_id = "ds-to-evict"
    other_id = "ds-keep"
    df = pd.DataFrame({"x": [1, 2]})

    # Populate two session entries that both reference the evicted dataset_id.
    nodes_module._session_cache["sess-A"] = {
        "frames": {dataset_id: df, other_id: df},
        "order": [dataset_id, other_id],
    }
    nodes_module._session_cache["sess-B"] = {
        "frames": {dataset_id: df},
        "order": [dataset_id],
    }
    nodes_module._session_cache["sess-C"] = {
        "frames": {other_id: df},
        "order": [other_id],
    }

    nodes_module.invalidate_dataset_cache(dataset_id)

    # The evicted dataset must not appear in any session's frames.
    for sid, entry in nodes_module._session_cache.items():
        assert dataset_id not in entry.get("frames", {}), (
            f"dataset_id still present in session {sid!r}"
        )

    # sess-A retains other_id; sess-B was emptied so it is dropped entirely.
    assert "sess-A" in nodes_module._session_cache
    assert other_id in nodes_module._session_cache["sess-A"]["frames"]
    assert "sess-B" not in nodes_module._session_cache
    assert "sess-C" in nodes_module._session_cache  # untouched


def test_invalidate_dataset_cache_noop_when_not_cached(_clear_session_cache):
    """Calling invalidate_dataset_cache for an unknown dataset_id is a no-op."""
    # Should not raise even when the cache is empty.
    nodes_module.invalidate_dataset_cache("totally-unknown-ds-id")
    assert nodes_module._session_cache == {}


def test_invalidate_dataset_cache_order_list_updated(_clear_session_cache):
    """The `order` list is kept consistent with `frames` after eviction."""
    dataset_id = "ds-ordered"
    other_id = "ds-other"
    df = pd.DataFrame({"y": [9]})

    nodes_module._session_cache["sess-X"] = {
        "frames": {dataset_id: df, other_id: df},
        "order": [dataset_id, other_id],
    }

    nodes_module.invalidate_dataset_cache(dataset_id)

    entry = nodes_module._session_cache.get("sess-X")
    assert entry is not None
    assert dataset_id not in entry["order"]
    assert other_id in entry["order"]


def test_invalidate_dataset_cache_empty_session_removed(_clear_session_cache):
    """When eviction empties a session's frames dict, that session entry is dropped."""
    dataset_id = "ds-only"
    df = pd.DataFrame({"z": [7]})

    nodes_module._session_cache["sess-only"] = {
        "frames": {dataset_id: df},
        "order": [dataset_id],
    }

    nodes_module.invalidate_dataset_cache(dataset_id)

    assert "sess-only" not in nodes_module._session_cache
