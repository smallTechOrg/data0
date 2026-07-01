"""Real-Gemini E2E for inline ECharts chart capture (C4, slice-4a).

Requires `AGENT_GEMINI_API_KEY` in `.env` (auto-detect selects the real Gemini
provider). The agent is asked to PLOT a clearly-chartable column via the
`echart(...)` helper; `execute_action` must capture the resulting ECharts `option`
dict as JSON into `result["charts"]`.

Driven via `run_agent(..., run_clarification=False, skip_clarification=True)` (mirrors
`test_preflight_real.py`'s dataset fixture + uploads_dir monkeypatch) against the
production SQLite driver (the isolated copy via `_isolated_db`). Asserts CONTENT:
at least one chart captured, and the first chart is a valid ECharts `option`
JSON object carrying a `series` key.
"""
from __future__ import annotations

import json

import numpy as np
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
            columns_json=[{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
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


@pytest.mark.usefixtures("_require_llm_key")
def test_real_gemini_captures_an_echart_chart(uploads_dir):
    """Ask the real model to chart a chartable column via echart(...) -> an ECharts
    option JSON (with a `series` key) is captured in result["charts"]."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "region": ["North", "South", "East", "West", "Central"],
            "sales": rng.integers(50, 500, size=5),
        }
    )
    dataset_id = _make_dataset(uploads_dir, "sales_by_region.csv", df)

    # An explicit, unambiguous plotting instruction so the model reliably calls
    # the echart() helper rather than describing a chart.
    question = (
        "Make a bar chart of `sales` by `region` using the echart helper, e.g. "
        "echart('bar', df, x='region', y='sales', title='Sales by region'). "
        "Return the option so it is captured, then give your FINAL ANSWER "
        "describing which region has the highest sales."
    )
    result = run_agent(
        question,
        [dataset_id],
        run_clarification=False,
        skip_clarification=True,
    )

    assert result["type"] == "answer", f"expected an answer, got {result.get('type')}"
    charts = result["charts"]
    assert isinstance(charts, list)
    assert len(charts) >= 1, (
        f"expected at least one captured ECharts chart; got {len(charts)}. "
        f"steps={[s.get('action') for s in result.get('action_history', [])]}"
    )

    # The first chart is a valid ECharts `option` JSON object with a series key
    # (NOT a Plotly figure — there is no data/layout envelope).
    option = json.loads(charts[0])
    assert isinstance(option, dict)
    assert "series" in option, (
        f"chart JSON is not an ECharts option (missing 'series'); "
        f"got keys {list(option.keys())}"
    )
    assert "data" not in option and "layout" not in option, (
        "chart JSON looks like a Plotly figure (has data/layout); expected an "
        "ECharts option"
    )
    print(f"\n[charts] captured {len(charts)} chart(s); chart[0] top-level keys: {sorted(option.keys())}")
    print(f"[charts] series count: {len(option['series'])}")
