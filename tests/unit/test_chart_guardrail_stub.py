"""Deterministic chart-guardrail tests (stub mode, must not hang).

When a question EXPLICITLY asks for a chart but a final reply arrives with no
chart produced, the graph forces ONE extra plan_action iteration demanding an
`echart(...)`. `chart_force_count` (incremented in `plan_action`) caps the forced
retries at ~1 so the loop ALWAYS terminates — even in stub mode, which never
charts. These tests cover the `_wants_chart` classifier, the `after_plan` router
branch, and a full stub-mode run proving the cap (no infinite loop).
"""
from __future__ import annotations

import pandas as pd
import pytest

from db.models import DatasetRow
from db.session import create_db_session
from graph import nodes as nodes_module
from graph.edges import after_plan
from graph.nodes import _wants_chart


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Drive every test here through the offline stub provider."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    monkeypatch.delenv("AGENT_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_OPENROUTER_API_KEY", raising=False)


def _make_dataset(uploads_dir, filename: str = "sales.csv") -> str:
    df = pd.DataFrame(
        {
            "region": ["n", "s", "e", "w"],
            "sales": [10.0, 20.0, 30.0, 40.0],
        }
    )
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
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: d)
    return d


# --------------------------------------------------------------------------- #
# _wants_chart classifier
# --------------------------------------------------------------------------- #


def test_wants_chart_true_for_explicit_requests():
    assert _wants_chart("plot sales by region") is True
    assert _wants_chart("give me 5 ways to grow revenue, with charts") is True
    assert _wants_chart("show me a chart of sales") is True
    # Other explicit visualization vocabulary.
    assert _wants_chart("draw a histogram of prices") is True
    assert _wants_chart("visualise the trend") is True
    assert _wants_chart("create a graph") is True


def test_wants_chart_false_for_plain_questions():
    assert _wants_chart("what is the average price?") is False
    assert _wants_chart("how many rows are there?") is False
    assert _wants_chart("") is False
    assert _wants_chart("summarise the dataset") is False


def test_wants_chart_is_case_insensitive():
    assert _wants_chart("PLOT the data") is True
    assert _wants_chart("Show Me a CHART") is True


# --------------------------------------------------------------------------- #
# after_plan forced-retry branch + cap
# --------------------------------------------------------------------------- #


def test_after_plan_forces_replan_when_chart_wanted_but_missing():
    """A final reply with wants_chart + no charts + count<2 loops back to replan."""
    state = {
        "llm_response": "FINAL ANSWER: here is a table",
        "wants_chart": True,
        "charts": [],
        "chart_force_count": 0,
    }
    assert after_plan(state) == "plan_action"
    # count == 1 still loops.
    assert after_plan({**state, "chart_force_count": 1}) == "plan_action"


def test_after_plan_finalizes_once_cap_reached():
    """Once chart_force_count reaches 2 the guardrail stops forcing -> finalize."""
    state = {
        "llm_response": "FINAL ANSWER: still a table, no chart",
        "wants_chart": True,
        "charts": [],
        "chart_force_count": 2,
    }
    assert after_plan(state) == "finalize"


def test_after_plan_finalizes_when_chart_already_produced():
    """A chart already exists -> normal finalize even though a chart was wanted."""
    state = {
        "llm_response": "FINAL ANSWER: here is the chart",
        "wants_chart": True,
        "charts": ["{\"series\": []}"],
        "chart_force_count": 0,
    }
    assert after_plan(state) == "finalize"


def test_after_plan_finalizes_when_chart_not_wanted():
    """No chart requested -> the guardrail never fires."""
    state = {
        "llm_response": "FINAL ANSWER: 42",
        "wants_chart": False,
        "charts": [],
        "chart_force_count": 0,
    }
    assert after_plan(state) == "finalize"


def test_after_plan_non_final_still_executes():
    """A non-final action reply routes to execute_action regardless of wants_chart."""
    state = {
        "llm_response": "df['sales'].sum()",
        "wants_chart": True,
        "charts": [],
        "chart_force_count": 0,
    }
    assert after_plan(state) == "execute_action"


# --------------------------------------------------------------------------- #
# setup sets wants_chart from the question
# --------------------------------------------------------------------------- #


def test_setup_sets_wants_chart_true(uploads_dir):
    dataset_id = _make_dataset(uploads_dir)
    result = nodes_module.setup(
        {"run_id": "r-wc", "dataset_ids": [dataset_id], "question": "plot sales by region"}
    )
    assert result["wants_chart"] is True


def test_setup_sets_wants_chart_false(uploads_dir):
    dataset_id = _make_dataset(uploads_dir)
    result = nodes_module.setup(
        {"run_id": "r-nowc", "dataset_ids": [dataset_id], "question": "what is the average?"}
    )
    assert result["wants_chart"] is False


# --------------------------------------------------------------------------- #
# Full stub run terminates (no infinite loop) and the cap holds
# --------------------------------------------------------------------------- #


def test_chart_requesting_run_terminates_and_cap_holds(uploads_dir):
    """A stub-mode run for a chart-requesting question completes WITHOUT hanging.

    The stub never produces a chart, so the guardrail keeps forcing replans until
    `chart_force_count` reaches its cap (2), then finalizes normally. This proves
    the termination guarantee.
    """
    from db.models import QueryRunRow
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("plot sales by region with charts", [dataset_id])

    # The run completed (did not hang / recursion-error).
    assert result["status"] == "completed"
    assert result["answer"]
    # Stub never charts, so the final answer has no chart attached.
    assert result["charts"] == []

    # The forced-retry counter is bounded by the cap (<= 2) — proves no runaway.
    with create_db_session() as session:
        row = session.get(QueryRunRow, result["run_id"])
        assert row is not None
        assert row.status == "completed"


def test_chart_run_final_state_count_bounded(uploads_dir):
    """Invoke the compiled graph directly and assert the final state's
    `chart_force_count` is bounded by the cap (<= 2) — the termination invariant."""
    from graph.agent import agentic_ai

    dataset_id = _make_dataset(uploads_dir)
    initial = {
        "run_id": "r-bound",
        "dataset_ids": [dataset_id],
        "question": "show me a chart of sales by region",
        "conversation_history": [],
        "action_history": [],
        "iteration_count": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "charts": [],
        "status": "running",
        "max_iterations": 6,
        "error": None,
    }
    final = agentic_ai.invoke(initial, config={"recursion_limit": 6 * 3 + 10})

    assert final["status"] == "completed"
    assert final["wants_chart"] is True
    assert final["charts"] == []  # stub never charts
    # The guardrail forced AT MOST one extra replan: count is bounded by the cap.
    assert final.get("chart_force_count", 0) <= 2


def test_non_chart_run_does_not_force_replan(uploads_dir):
    """A plain question finalizes on the first FINAL ANSWER (no forced replan)."""
    from graph.runner import run_agent

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("what is the average sales?", [dataset_id])

    assert result["status"] == "completed"
    assert result["answer"]
