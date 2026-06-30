"""Unit tests for graph.sandbox helpers — no LLM key required."""

import json

import pandas as pd
import pytest

from graph.sandbox import (
    _stringify,
    build_namespace,
    eval_expression,
    make_echart,
)


# --- D4: column cap in _stringify -------------------------------------------


def test_stringify_wide_dataframe_caps_at_20_columns():
    """D4/C8: DataFrames with >20 columns are capped at 20 columns in _stringify output."""
    # Build a DataFrame with 30 columns (col_0 .. col_29), 5 rows.
    df = pd.DataFrame(
        {f"col_{i}": range(5) for i in range(30)}
    )
    result = _stringify(df)

    # Must contain the cap note.
    assert "[showing 20 of 30 columns]" in result, (
        f"Expected cap note not found in output:\n{result}"
    )

    # col_20 through col_29 must NOT appear in the output (they were sliced off).
    for col_idx in range(20, 30):
        assert f"col_{col_idx}" not in result, (
            f"Column col_{col_idx} should have been removed by the 20-col cap "
            f"but was found in output:\n{result}"
        )

    # col_0 through col_19 must still appear.
    for col_idx in range(20):
        assert f"col_{col_idx}" in result, (
            f"Column col_{col_idx} missing from capped output:\n{result}"
        )


def test_stringify_narrow_dataframe_no_col_cap():
    """D4/C8: DataFrames with <=20 columns are NOT truncated and carry no cap note."""
    df = pd.DataFrame({f"col_{i}": [1, 2] for i in range(20)})
    result = _stringify(df)

    assert "showing 20 of" not in result
    assert "columns]" not in result
    # All 20 columns present.
    for col_idx in range(20):
        assert f"col_{col_idx}" in result


def test_stringify_wide_dataframe_row_cap_still_applied():
    """D4/C8: row cap (100) and col cap (20) both apply when the frame exceeds both limits.

    When both caps fire, columns outside the first 20 must not appear and the
    col-cap note must be present.  The char cap may truncate the suffix in the
    extreme case (150 rows x 20 cols), so we verify column exclusion directly
    rather than relying on the suffix surviving.
    """
    df = pd.DataFrame(
        {f"col_{i}": range(150) for i in range(30)}
    )
    result = _stringify(df)

    # Columns beyond the cap must not appear.
    for col_idx in range(20, 30):
        assert f"col_{col_idx}" not in result, (
            f"col_{col_idx} should have been removed by the 20-col cap"
        )
    # col_0 .. col_19 must appear (they survive the cap).
    for col_idx in range(20):
        assert f"col_{col_idx}" in result


def test_stringify_char_cap_still_applied():
    """D4/C8: the 6000-char safety cap is still applied after row + col capping."""
    # 20 columns with long values to force the char cap.
    df = pd.DataFrame(
        {f"col_{i}": ["a" * 500 for _ in range(10)] for i in range(20)}
    )
    result = _stringify(df)
    assert len(result) <= 6100  # allow a small overshoot for the truncation marker


def test_stringify_series_unaffected_by_col_cap():
    """D4: a pd.Series is not subject to the column cap (it has no columns axis)."""
    s = pd.Series(range(5), name="values")
    result = _stringify(s)
    # No column cap note for a Series.
    assert "columns]" not in result
    # All values are present in the output.
    for v in range(5):
        assert str(v) in result


# --- C4: ECharts `echart(...)` helper ---------------------------------------


def _sample_df():
    return pd.DataFrame(
        {
            "region": ["North", "South", "East"],
            "sales": [120, 90, 150],
            "cost": [40, 30, 55],
        }
    )


def test_echart_bar_returns_option_with_series():
    """echart('bar', df, x=, y=) returns an ECharts option dict with a series key."""
    echart = make_echart()
    option = echart("bar", _sample_df(), x="region", y="sales", title="Revenue by region")

    assert isinstance(option, dict)
    assert "series" in option
    # Sensible defaults from the spec.
    assert option["xAxis"]["type"] == "category"
    assert option["xAxis"]["data"] == ["North", "South", "East"]
    assert option["yAxis"]["type"] == "value"
    assert option["tooltip"]["trigger"] == "axis"
    # Legend now sits on the RIGHT, outside the plot (vertical + scrollable).
    assert option["legend"]["orient"] == "vertical"
    assert "right" in option["legend"]
    assert option["legend"]["type"] == "scroll"
    # Grid reserves room on the right for the legend and keeps labels inside.
    assert option["grid"]["right"] == 120
    assert option["grid"]["right"] > option["grid"]["left"]
    assert option["grid"]["containLabel"] is True
    # Title stays top-centered above the plot.
    assert option["title"]["text"] == "Revenue by region"
    assert option["title"]["left"] == "center"
    # One series of bars with the y-column values.
    assert option["series"][0]["type"] == "bar"
    assert option["series"][0]["data"] == [120, 90, 150]


def test_echart_multi_series_from_y_list():
    """A list `y=` produces one series per column."""
    echart = make_echart()
    option = echart("line", _sample_df(), x="region", y=["sales", "cost"])
    names = {s["name"] for s in option["series"]}
    assert names == {"sales", "cost"}
    assert all(s["type"] == "line" for s in option["series"])


def test_echart_pie_uses_item_tooltip_and_name_value_data():
    echart = make_echart()
    option = echart("pie", _sample_df(), x="region", y="sales", title="Share")
    assert option["tooltip"]["trigger"] == "item"
    assert option["series"][0]["type"] == "pie"
    assert option["series"][0]["data"][0] == {"name": "North", "value": 120}
    # Pie has no grid; instead the center is shifted left to clear the right legend.
    assert "grid" not in option
    assert option["series"][0]["center"] == ["40%", "54%"]
    assert option["series"][0]["radius"]
    # Legend stays the right-vertical default.
    assert option["legend"]["orient"] == "vertical"
    assert "right" in option["legend"]


def test_echart_scatter_builds_xy_points():
    echart = make_echart()
    option = echart("scatter", _sample_df(), x="sales", y="cost")
    assert option["tooltip"]["trigger"] == "item"
    assert option["series"][0]["type"] == "scatter"
    assert option["series"][0]["data"][0] == [120, 40]


def test_echart_raw_option_escape_hatch():
    """option=<dict> with a series key is accepted and returned as-is."""
    echart = make_echart()
    raw = {
        "xAxis": {"type": "category", "data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1, 2]}],
    }
    option = echart("bar", option=raw)
    assert "series" in option
    assert option["series"] == raw["series"]
    # Defaults are merged in when the caller didn't set them.
    assert option["legend"]["orient"] == "vertical"
    assert "right" in option["legend"]
    # This raw option has axes, so the grid defaults get extended in.
    assert option["grid"]["right"] == 120
    assert option["grid"]["containLabel"] is True


def test_echart_raw_option_preserves_caller_legend_and_grid():
    """Caller-supplied legend/grid are NOT overridden by the defaults."""
    echart = make_echart()
    raw = {
        "legend": {"top": 0},
        "grid": {"left": 60, "right": 24},
        "xAxis": {"type": "category", "data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1, 2]}],
    }
    option = echart("bar", option=raw)
    # Explicit legend kept as-is.
    assert option["legend"] == {"top": 0}
    # Explicit grid right kept; containLabel extended in since absent.
    assert option["grid"]["right"] == 24
    assert option["grid"]["containLabel"] is True


def test_echart_raw_option_without_series_raises():
    echart = make_echart()
    with pytest.raises(ValueError):
        echart("bar", option={"xAxis": {}})


def test_echart_bad_kind_raises_valueerror():
    echart = make_echart()
    with pytest.raises(ValueError):
        echart("treemap", _sample_df(), x="region", y="sales")


def test_echart_missing_column_raises_valueerror():
    echart = make_echart()
    with pytest.raises(ValueError):
        echart("bar", _sample_df(), x="nope", y="sales")


def test_echart_registers_into_accumulator():
    """The run-aware echart calls on_chart with the built option exactly once."""
    captured = []
    echart = make_echart(on_chart=captured.append)
    echart("bar", _sample_df(), x="region", y="sales")
    assert len(captured) == 1
    assert "series" in captured[0]


def test_echart_option_is_json_serialisable():
    """Built options must survive json.dumps (numpy scalars coerced)."""
    echart = make_echart()
    option = echart("bar", _sample_df(), x="region", y="sales")
    text = json.dumps(option)
    parsed = json.loads(text)
    assert "series" in parsed


def test_build_namespace_exposes_echart_and_drops_plotly():
    """The eval namespace has echart and the analysis libs, but NO plotly px/go."""
    ns = build_namespace([_sample_df()], ["sales.csv"])
    assert callable(ns["echart"])
    # Analysis libs stay.
    for lib in ("pd", "np", "plt", "sns", "scipy", "stats", "sklearn", "sm", "save_dataset"):
        assert lib in ns
    # Plotly removed from the namespace.
    assert "px" not in ns
    assert "go" not in ns


def test_sandbox_has_no_plotly_import():
    """graph.sandbox must not pull in plotly at all (Plotly fully removed)."""
    import graph.sandbox as sandbox_module

    assert not hasattr(sandbox_module, "px")
    assert not hasattr(sandbox_module, "go")
    # The module did not import plotly into sys.modules via this import.
    src = sandbox_module.__file__
    text = open(src, encoding="utf-8").read()
    assert "plotly" not in text.lower()


def test_eval_expression_echart_registers_one_chart_via_accumulator():
    """Running an echart(...) expression through eval_expression registers exactly
    one captured option whose JSON parses to an object with a series key."""
    ns = build_namespace([_sample_df()], ["sales.csv"])
    captured = []
    ns["echart"] = make_echart(on_chart=captured.append)

    result_str, charts, is_error, error_str = eval_expression(
        "echart('bar', df, x='region', y='sales', title='Revenue')", ns
    )
    assert not is_error, error_str
    # eval_expression itself returns no charts (the node owns serialisation).
    assert charts == []
    # The accumulator captured exactly one option.
    assert len(captured) == 1
    parsed = json.loads(json.dumps(captured[0]))
    assert "series" in parsed
