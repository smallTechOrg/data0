"""Unit tests: chart rule table (C41) and v2 domain models / upgrade_v1."""
import copy

import pytest
from pydantic import ValidationError

from domain.dashboard import DashboardSpec, Widget, upgrade_v1
from graph.dashboard_charts import (
    CHART_RULES,
    clamp_chart_type,
    rationale_for,
    rules_text,
    suggest,
)


def col(name, alias, role, nunique):
    return {"name": name, "dtype_alias": alias, "role": role, "nunique": nunique}


DATE = col("order_date", "datetime", "time", 24)
REGION = col("region", "text", "dimension", 4)
PRODUCT = col("product", "text", "dimension", 20)
REV = col("revenue", "float", "measure", 500)
QTY = col("qty", "float", "measure", 90)
PROFILE = {"columns": [DATE, REGION, PRODUCT, REV, QTY]}


# ---- clamp_chart_type -------------------------------------------------------
def test_pie_over_eight_categories_becomes_bar_with_note():
    t, note = clamp_chart_type("pie", PRODUCT)
    assert t == "bar" and "converted to bar" in note


def test_pie_top_n_limit_keeps_pie():
    assert clamp_chart_type("pie", PRODUCT, limit=6) == ("pie", None)


def test_pie_boundary_eight_ok_nine_clamped():
    assert clamp_chart_type("pie", col("a", "text", "dimension", 8))[0] == "pie"
    assert clamp_chart_type("pie", col("a", "text", "dimension", 9))[0] == "bar"


def test_line_on_categorical_becomes_bar():
    t, note = clamp_chart_type("line", REGION)
    assert t == "bar" and note


def test_line_on_datetime_unchanged():
    assert clamp_chart_type("line", DATE) == ("line", None)
    assert clamp_chart_type("area", DATE) == ("area", None)


def test_unknown_x_never_raises():
    assert clamp_chart_type("pie", None) == ("pie", None)


# ---- suggest ---------------------------------------------------------------
def test_suggest_time_measure_leads_with_line():
    assert suggest(DATE, REV)[0] == "line"


def test_suggest_small_categorical_bar_or_pie_by_intent():
    assert suggest(REGION, REV) == ["bar", "pie"]
    assert suggest(REGION, REV, parts_of_whole=True)[0] == "pie"


def test_suggest_large_categorical_bar_only_no_pie():
    assert suggest(PRODUCT, REV) == ["bar"]


def test_suggest_two_numerics_scatter_and_single_numeric_histogram():
    assert suggest(QTY, REV)[0] == "scatter"
    assert suggest(REV)[0] == "histogram"


def test_suggest_no_x_never_empty():
    assert suggest(None) == ["bar"]


# ---- rationale_for ---------------------------------------------------------
@pytest.mark.parametrize(
    "chart",
    [
        {"type": "line", "x": "order_date", "y": {"field": "revenue", "agg": "sum"}},
        {"type": "pie", "x": "region", "y": {"field": "revenue", "agg": "sum"}},
        {"type": "bar", "x": "product", "limit": 10},
        {"type": "bar", "x": "region"},
        {"type": "scatter", "x": "qty", "y": {"field": "revenue", "agg": "none"}},
        {"type": "histogram", "x": "revenue"},
    ],
)
def test_rationale_nonempty_bounded_and_cites_x(chart):
    r = rationale_for(chart, PROFILE)
    assert 0 < len(r) <= 140 and chart["x"] in r


def test_rationale_unknown_column_does_not_raise():
    assert rationale_for({"type": "bar", "x": "ghost"}, PROFILE)


def test_rules_table_and_prompt_text():
    assert any(r["chart"] == "pie" for r in CHART_RULES)
    txt = rules_text()
    assert "line" in txt and "histogram" in txt


# ---- domain v2 -------------------------------------------------------------
def _w(**kw):
    base = {"id": "k1", "kind": "kpi", "title": "T", "kpi": {"agg": "count"}}
    base.update(kw)
    return base


def test_widget_v2_defaults_and_limits():
    w = Widget.model_validate(_w())
    assert w.priority == 1 and w.description_source == "auto" and w.chart_rationale is None
    with pytest.raises(ValidationError):
        Widget.model_validate(_w(description="x" * 201))
    with pytest.raises(ValidationError):
        Widget.model_validate(_w(chart_rationale="x" * 141))
    with pytest.raises(ValidationError):
        Widget.model_validate(_w(description_source="bogus"))
    with pytest.raises(ValidationError):
        Widget.model_validate(_w(priority=0))


def test_spec_v2_accepts_summary_and_v1_version():
    s = DashboardSpec.model_validate({"title": "D", "summary": "s", "widgets": [_w()]})
    assert s.version == 2
    assert DashboardSpec.model_validate({"version": 1, "title": "D", "widgets": [_w()]})
    with pytest.raises(ValidationError):
        DashboardSpec.model_validate({"title": "D", "summary": "x" * 201, "widgets": [_w()]})


V1 = {
    "version": 1,
    "title": "Old",
    "description": None,
    "widgets": [
        {"id": "c1", "kind": "chart", "title": "C", "layout": {"x": 0, "y": 2, "w": 6, "h": 5},
         "chart": {"type": "bar", "x": "region", "y": {"field": "revenue", "agg": "sum"}}},
        {"id": "k2", "kind": "kpi", "title": "K2", "layout": {"x": 3, "y": 0, "w": 3, "h": 2},
         "kpi": {"field": "revenue", "agg": "sum"}},
        {"id": "k1", "kind": "kpi", "title": "K1", "layout": {"x": 0, "y": 0, "w": 3, "h": 2},
         "kpi": {"agg": "count"}},
    ],
}


def test_upgrade_v1_reading_order_priorities_and_captions():
    before = copy.deepcopy(V1)
    v2 = upgrade_v1(V1)
    assert V1 == before  # input untouched
    assert v2["version"] == 2 and v2["summary"] is None
    prio = {w["id"]: w["priority"] for w in v2["widgets"]}
    assert prio == {"k1": 1, "k2": 2, "c1": 3}
    assert all(w["description"] and w["description_source"] == "auto" for w in v2["widgets"])
    DashboardSpec.model_validate(v2)


def test_upgrade_v1_idempotent_and_preserves_existing_text():
    once = upgrade_v1(V1)
    assert upgrade_v1(once) == once
    v1 = copy.deepcopy(V1)
    v1["widgets"][0]["description"] = "Keep me"
    out = upgrade_v1(v1)
    kept = next(w for w in out["widgets"] if w["id"] == "c1")
    assert kept["description"] == "Keep me"


def test_upgrade_v1_widgets_without_layout_sort_last():
    v1 = copy.deepcopy(V1)
    del v1["widgets"][0]["layout"]
    prio = {w["id"]: w["priority"] for w in upgrade_v1(v1)["widgets"]}
    assert prio["c1"] == 3
