"""Offline unit tests for the C41 pipeline: priorities, text defaults, chart
clamps, `assign_layout` v2, fallback ranking and `build_insights`. No LLM, no DB."""
from __future__ import annotations

import numpy as np
import pandas as pd

from graph.dashboard import assign_layout, auto_caption, fallback_spec, normalize_priorities, validate_spec
from graph.dashboard_data import build_insights, compute_widget_data
from graph.dashboard_profile import profile_dataframe


def _df(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    return pd.DataFrame(
        {
            "order_date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "region": rng.choice(["N", "S", "E"], n),
            "product": [f"P{i % 20}" for i in range(n)],
            "units": rng.integers(1, 9, n),
            "revenue": rng.gamma(2, 50, n).round(2),
        }
    )


def _kpi(wid="k", **over):
    return {"id": wid, "kind": "kpi", "title": "Total", "kpi": {"field": "revenue", "agg": "sum"}, **over}


def _chart(wid="c", chart=None, **over):
    cfg = {"type": "bar", "x": "region", "y": {"field": "revenue", "agg": "sum"}, **(chart or {})}
    return {"id": wid, "kind": "chart", "title": "Chart", "chart": cfg, **over}


def _validate(*widgets, notes=None):
    profile = profile_dataframe(_df())
    return validate_spec({"widgets": list(widgets)}, profile["columns_schema"], profile=profile, notes=notes)


def _ranks(widgets):
    return [w["priority"] for w in widgets]


# --- normalize_priorities ----------------------------------------------------


def test_duplicate_missing_and_out_of_range_priorities_become_dense():
    got = normalize_priorities(
        [
            {"id": "a", "priority": 5},
            {"id": "b"},
            {"id": "c", "priority": 5},
            {"id": "d", "priority": 2},
            {"id": "e", "priority": 0},
            {"id": "f", "priority": "1"},
            {"id": "g", "priority": True},
        ]
    )
    assert {w["id"]: w["priority"] for w in got} == {"d": 1, "a": 2, "c": 3, "b": 4, "e": 5, "f": 6, "g": 7}
    assert [w["id"] for w in got] == list("abcdefg")  # list position is untouched


def test_all_missing_priorities_follow_reply_order():
    clean, errors = _validate(_kpi("a"), _chart("b"), _kpi("c"))
    assert errors == [] and _ranks(clean) == [1, 2, 3]


# --- text fields -------------------------------------------------------------


def test_missing_text_is_filled_and_tagged_auto():
    clean, _ = _validate(_kpi(), _chart())
    for w in clean:
        assert w["description"] and w["description_source"] == "auto"
    assert "200 rows" in clean[0]["description"]
    assert clean[1]["chart_rationale"]
    assert clean[0]["chart_rationale"] is None  # charts only


def test_agent_text_is_kept_tagged_and_truncated():
    clean, _ = _validate(
        _chart(description="  Why\n it   matters " + "x" * 300, chart_rationale="y" * 300)
    )
    w = clean[0]
    assert w["description"].startswith("Why it matters ") and len(w["description"]) == 200
    assert w["description_source"] == "agent"
    assert len(w["chart_rationale"]) == 140


def test_non_string_text_falls_back_to_auto():
    clean, _ = _validate(_kpi(description=123))
    assert clean[0]["description_source"] == "auto" and isinstance(clean[0]["description"], str)


def test_validation_is_idempotent_with_v2_fields():
    profile = profile_dataframe(_df())
    first, _ = _validate(_kpi(priority=2), _chart(priority=1, description="Agent words."))
    again, errors = validate_spec({"widgets": first}, profile["columns_schema"], profile=profile)
    assert errors == [] and again == first


def test_auto_caption_mentions_filter_scope():
    widget = _kpi(filters=[{"field": "region", "op": "eq", "value": "N"}])
    assert "filtered" in auto_caption(widget, profile_dataframe(_df()))


def test_auto_caption_says_top_n_only_for_truncated_categories():
    profile = profile_dataframe(_df())
    top = auto_caption(_chart(chart={"x": "product", "limit": 5}), profile)
    trend = auto_caption(_chart(chart={"type": "line", "x": "order_date", "limit": 5}), profile)
    assert "top 5" in top and "top" not in trend


# --- chart clamps ------------------------------------------------------------


def test_pie_with_too_many_categories_becomes_sorted_bar_with_note():
    notes: list[str] = []
    clean, errors = _validate(
        _chart(chart={"type": "pie", "x": "product"}, chart_rationale="A pie is great."), notes=notes
    )
    assert errors == []
    chart = clean[0]["chart"]
    assert chart["type"] == "bar" and chart["sort"] == "y_desc"
    assert "A pie is great." not in clean[0]["chart_rationale"]  # stale justification replaced
    assert len(notes) == 1 and "product" in notes[0]


def test_small_pie_and_its_rationale_are_kept():
    clean, errors = _validate(_chart(chart={"type": "pie"}, chart_rationale="Few regions, so shares read well."))
    assert errors == []
    assert clean[0]["chart"]["type"] == "pie"
    assert clean[0]["chart_rationale"] == "Few regions, so shares read well."


def test_line_on_unordered_x_becomes_bar_with_note():
    notes: list[str] = []
    clean, errors = _validate(_chart(chart={"type": "line"}), notes=notes)
    assert errors == [] and clean[0]["chart"]["type"] == "bar" and notes


def test_line_on_time_x_is_not_clamped():
    notes: list[str] = []
    clean, errors = _validate(_chart(chart={"type": "line", "x": "order_date"}), notes=notes)
    assert errors == [] and clean[0]["chart"]["type"] == "line" and notes == []


def test_without_a_profile_line_on_text_stays_a_validation_error():
    _, errors = validate_spec(
        {"widgets": [_chart(chart={"type": "line"})]}, {"region": "text", "revenue": "float"}
    )
    assert [e["code"] for e in errors] == ["axis_dtype_mismatch"]


# --- assign_layout v2 --------------------------------------------------------


def test_assign_layout_v2_contract_vector():
    widgets = [
        {"id": "a", "kind": "kpi", "priority": 2},
        {"id": "b", "kind": "kpi", "priority": 1},
        {"id": "c", "kind": "chart", "priority": 4},
        {"id": "d", "kind": "table", "priority": 3},
        {"id": "e", "kind": "chart", "priority": 5},
    ]
    got = [(w["id"], w["layout"]["x"], w["layout"]["y"]) for w in assign_layout(widgets)]
    assert got == [("b", 0, 0), ("a", 3, 0), ("d", 0, 2), ("c", 0, 8), ("e", 6, 8)]


# --- fallback ----------------------------------------------------------------


def test_fallback_ranks_measure_kpis_then_charts_then_table_then_rows():
    spec = fallback_spec(profile_dataframe(_df()), "x")
    assert spec["version"] == 2 and spec["summary"]
    by_rank = sorted(spec["widgets"], key=lambda w: w["priority"])
    assert _ranks(by_rank) == list(range(1, len(by_rank) + 1))
    assert by_rank[-1]["title"] == "Rows"
    kinds = [w["kind"] for w in by_rank[:-1]]
    assert kinds == sorted(kinds, key=["kpi", "chart", "table"].index)
    assert all(w["description"] for w in spec["widgets"])


# --- build_insights ----------------------------------------------------------


def test_insights_are_kpi_only_ordered_capped_and_full_data():
    df = _df()
    widgets = [_kpi(f"k{i}", priority=8 - i, description=f"why {i}") for i in range(8)]
    widgets.append(_chart("c", priority=9))
    clean, errors = _validate(*widgets)
    assert errors == []
    spec = {"widgets": clean}
    data = compute_widget_data(df, spec)
    insights = build_insights(spec, data)
    assert [i["rank"] for i in insights] == [1, 2, 3, 4, 5, 6]
    assert [i["widget_id"] for i in insights] == ["k7", "k6", "k5", "k4", "k3", "k2"]
    assert insights[0]["why"] == "why 7"
    assert insights[0]["headline"] == data["k7"]["formatted"]
    assert abs(data["k7"]["value"] - df["revenue"].sum()) < 1e-6


def test_insight_for_a_failed_kpi_shows_a_dash():
    spec = {"widgets": [_kpi(priority=1, description="d")]}
    got = build_insights(spec, {"k": {"status": "error", "message": "boom"}})
    assert got[0]["headline"] == "—" and got[0]["why"] == "d"
