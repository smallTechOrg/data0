"""Offline unit tests for `validate_spec`, `assign_layout`, `validate_layout`,
`fallback_spec` (C40, Phase 15). No LLM, no DB."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from graph.dashboard import assign_layout, fallback_spec, validate_layout, validate_spec
from graph.dashboard_profile import profile_dataframe

SCHEMA = {
    "order_id": "integer",
    "order_date": "datetime",
    "Region": "text",
    "category": "text",
    "units": "integer",
    "revenue": "float",
}


def _kpi(**over):
    cfg = {"field": "revenue", "agg": "sum", "format": "currency"}
    cfg.update(over)
    return {"id": "w1", "kind": "kpi", "title": "Total revenue", "kpi": cfg}


def _chart(**over):
    cfg = {"type": "bar", "x": "Region", "y": {"field": "revenue", "agg": "sum"}, "limit": 10}
    cfg.update(over)
    return {"id": "w2", "kind": "chart", "title": "Revenue by region", "chart": cfg}


def _table(**over):
    cfg = {
        "group_by": ["category"],
        "aggs": [{"field": "revenue", "agg": "sum", "alias": "revenue"}],
        "sort_by": "revenue",
        "limit": 10,
    }
    cfg.update(over)
    return {"id": "w3", "kind": "table", "title": "Top categories", "table": cfg}


def _validate(*widgets):
    return validate_spec({"title": "T", "widgets": list(widgets)}, SCHEMA)


def _codes(errors):
    return [e["code"] for e in errors]


def test_valid_spec_passes():
    clean, errors = _validate(_kpi(), _chart(), _table())
    assert errors == []
    assert [w["kind"] for w in clean] == ["kpi", "chart", "table"]
    assert clean[0]["kpi"]["agg"] == "sum"
    assert clean[2]["table"]["group_by"] == ["category"]


def test_unknown_field_snapped_case_insensitively():
    clean, errors = _validate(_kpi(field="REVENUE"), _chart(x="  region "))
    assert errors == []
    assert clean[0]["kpi"]["field"] == "revenue"
    assert clean[1]["chart"]["x"] == "Region"


def test_unknown_field_is_an_error_and_widget_dropped():
    clean, errors = _validate(_kpi(field="profit"), _chart())
    assert _codes(errors) == ["unknown_field"]
    assert errors[0]["widget_index"] == 0
    assert [w["kind"] for w in clean] == ["chart"]


def test_ambiguous_case_insensitive_match_is_unknown():
    schema = {"Sales": "float", "sales": "float"}
    _, errors = validate_spec({"widgets": [_kpi(field="SALES")]}, schema)
    assert _codes(errors) == ["unknown_field"]


def test_sum_on_text_is_dtype_mismatch():
    _, errors = _validate(_kpi(field="category", agg="sum"))
    assert _codes(errors) == ["agg_dtype_mismatch"]


def test_min_max_allow_datetime_but_not_text():
    clean, errors = _validate(_kpi(field="order_date", agg="max"))
    assert errors == [] and clean
    _, errors = _validate(_kpi(field="category", agg="min"))
    assert _codes(errors) == ["agg_dtype_mismatch"]


def test_bad_agg_and_count_without_field():
    _, errors = _validate(_kpi(agg="stdev"))
    assert _codes(errors) == ["bad_agg"]
    clean, errors = _validate(_kpi(field=None, agg="count"))
    assert errors == [] and clean[0]["kpi"]["field"] is None
    _, errors = _validate(_kpi(field=None, agg="sum"))
    assert _codes(errors) == ["bad_agg"]


def test_histogram_on_text_rejected_numeric_ok():
    _, errors = _validate(_chart(type="histogram", x="category", y=None))
    assert _codes(errors) == ["axis_dtype_mismatch"]
    clean, errors = _validate(_chart(type="histogram", x="revenue", y=None, bins=500))
    assert errors == []
    assert clean[0]["chart"]["bins"] == 50  # clamped
    assert clean[0]["chart"]["y"] is None


def test_chart_type_and_axis_rules():
    _, errors = _validate(_chart(type="radar"))
    assert _codes(errors) == ["bad_chart_type"]
    _, errors = _validate(_chart(type="line", x="category"))
    assert _codes(errors) == ["axis_dtype_mismatch"]
    _, errors = _validate(_chart(type="pie", x="units"))
    assert _codes(errors) == ["axis_dtype_mismatch"]
    _, errors = _validate(_chart(type="scatter", x="Region", y={"field": "revenue", "agg": "none"}))
    assert _codes(errors) == ["axis_dtype_mismatch"]
    clean, errors = _validate(_chart(type="scatter", x="units", y={"field": "revenue", "agg": "sum"}))
    assert errors == [] and clean[0]["chart"]["y"]["agg"] == "none"
    _, errors = _validate(_chart(y={"field": "revenue", "agg": "none"}))
    assert _codes(errors) == ["bad_agg"]


def test_time_grain_only_for_datetime_x():
    clean, _ = _validate(_chart(type="line", x="order_date", time_grain="month"))
    assert clean[0]["chart"]["time_grain"] == "month"
    clean, _ = _validate(_chart(type="bar", x="Region", time_grain="month"))
    assert clean[0]["chart"]["time_grain"] is None


def test_limits_clamped():
    clean, errors = _validate(_chart(limit=9999), _table(limit=0))
    assert errors == []
    assert clean[0]["chart"]["limit"] == 50
    assert clean[1]["table"]["limit"] == 1


def test_duplicate_and_missing_ids_repaired():
    a, b, c = _kpi(), _kpi(), _kpi()
    b.pop("id")
    c["id"] = "Not A Valid Id!"
    clean, errors = _validate(a, b, c)
    assert errors == []
    ids = [w["id"] for w in clean]
    assert len(set(ids)) == 3
    assert all(i.startswith("w") for i in ids)


def test_too_many_widgets():
    clean, errors = _validate(*[_kpi() for _ in range(14)])
    assert len(clean) == 12
    assert _codes(errors) == ["too_many_widgets", "too_many_widgets"]


def test_table_modes_mutually_exclusive():
    _, errors = _validate(_table(columns=["category"]))
    assert _codes(errors) == ["bad_table_mode"]
    _, errors = _validate(_table(group_by=None, aggs=None))
    assert _codes(errors) == ["bad_table_mode"]
    clean, errors = _validate(
        _table(group_by=None, aggs=None, columns=["category", "revenue"], sort_by="revenue")
    )
    assert errors == [] and clean[0]["table"]["columns"] == ["category", "revenue"]


def test_filters_validation():
    f_ok = [
        {"field": "units", "op": "gte", "value": 5},
        {"field": "Region", "op": "in", "value": ["N", "S"]},
    ]
    clean, errors = _validate({**_kpi(), "filters": f_ok})
    assert errors == [] and len(clean[0]["filters"]) == 2
    for bad in (
        {"field": "units", "op": "gte", "value": "abc"},
        {"field": "Region", "op": "gt", "value": "N"},
        {"field": "Region", "op": "like", "value": "N"},
        {"field": "Region", "op": "in", "value": "N"},
        {"field": "nope", "op": "eq", "value": 1},
    ):
        _, errors = _validate({**_kpi(), "filters": [bad]})
        assert len(errors) == 1, bad
    clean, errors = _validate({**_kpi(), "filters": [{"field": "units", "op": "not_null"}]})
    assert errors == [] and clean[0]["filters"][0]["value"] is None


@pytest.mark.parametrize(
    "reply",
    [None, [], "text", {"title": "x"}, {"widgets": "nope"}],
)
def test_whole_reply_shape_errors(reply):
    clean, errors = validate_spec(reply, SCHEMA)
    assert clean == [] and _codes(errors) == ["bad_shape"]
    assert errors[0]["widget_index"] is None


def test_unknown_kind_and_missing_block():
    _, errors = _validate({"id": "w1", "kind": "gauge", "title": "x"})
    assert _codes(errors) == ["unknown_kind"]
    _, errors = _validate({"id": "w1", "kind": "kpi", "title": "x"})
    assert _codes(errors) == ["bad_shape"]
    _, errors = _validate("not a widget")
    assert _codes(errors) == ["bad_shape"]


def test_validate_spec_is_idempotent_on_clean_output():
    clean, _ = _validate(_kpi(), _chart(), _table())
    again, errors = validate_spec({"widgets": copy.deepcopy(clean)}, SCHEMA)
    assert errors == [] and again == clean


# --- layout ------------------------------------------------------------------


def test_assign_layout_matches_contract_vector():
    kinds = ["kpi", "kpi", "kpi", "kpi", "chart", "chart", "table"]
    widgets = [{"id": f"w{i}", "kind": k} for i, k in enumerate(kinds)]
    placed = assign_layout(list(reversed(widgets)))  # kind order wins over input order
    got = [
        (w["kind"], w["layout"]["x"], w["layout"]["y"], w["layout"]["w"], w["layout"]["h"])
        for w in placed
    ]
    assert got == [
        ("kpi", 0, 0, 3, 2),
        ("kpi", 3, 0, 3, 2),
        ("kpi", 6, 0, 3, 2),
        ("kpi", 9, 0, 3, 2),
        ("chart", 0, 2, 6, 5),
        ("chart", 6, 2, 6, 5),
        ("table", 0, 7, 12, 6),
    ]


def test_assign_layout_keeps_existing_size_and_never_overlaps():
    widgets = [
        {"id": "a", "kind": "chart", "layout": {"x": 0, "y": 0, "w": 12, "h": 3}},
        {"id": "b", "kind": "kpi"},
        {"id": "c", "kind": "kpi", "layout": {"x": 5, "y": 5, "w": 7, "h": 2}},
    ]
    placed = assign_layout(widgets)
    clean, err = validate_layout(
        [{"id": w["id"], **w["layout"]} for w in placed], [w["id"] for w in widgets]
    )
    assert err is None
    by_id = {w["id"]: w["layout"] for w in placed}
    assert (by_id["a"]["w"], by_id["a"]["h"]) == (12, 3)
    assert (by_id["c"]["w"], by_id["c"]["h"]) == (7, 2)


def test_validate_layout_rules():
    ids = ["a", "b"]
    a = {"id": "a", "x": 0, "y": 0, "w": 6, "h": 2}
    b = {"id": "b", "x": 6, "y": 0, "w": 6, "h": 2}
    clean, err = validate_layout([a, b], ids)
    assert err is None and len(clean) == 2
    cases = {
        "overlap": [a, {**b, "x": 5, "y": 1}],
        "out_of_bounds": [{**a, "x": 8}, {**b, "x": 0, "y": 5}],
        "negative": [{**a, "x": -1}, b],
        "zero_w": [{**a, "w": 0}, b],
        "missing": [a],
        "unknown": [a, {**b, "id": "zz"}],
        "duplicate": [a, {**b, "id": "a"}],
        "float": [{**a, "x": 0.5}, b],
        "bool": [{**a, "x": True}, b],
    }
    for name, layout in cases.items():
        clean, err = validate_layout(layout, ids)
        assert clean is None and err, name
    assert validate_layout([], ids)[1]
    assert validate_layout("x", ids)[1]


# --- fallback ----------------------------------------------------------------


def test_fallback_spec_has_kpi_chart_table_and_valid_fields():
    rng = np.random.default_rng(0)
    n = 120
    df = pd.DataFrame(
        {
            "order_id": np.arange(n),
            "order_date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "region": rng.choice(["N", "S", "E"], n),
            "revenue": rng.normal(100, 10, n),
            "units": rng.integers(1, 40, n),
        }
    )
    profile = profile_dataframe(df)
    spec = fallback_spec(profile, "anything")
    kinds = [w["kind"] for w in spec["widgets"]]
    assert kinds.count("kpi") >= 2 and "chart" in kinds and "table" in kinds
    clean, errors = validate_spec(spec, profile["columns_schema"])
    assert errors == [] and len(clean) == len(spec["widgets"])
    # first KPI is the row count; the id column is never summed
    assert spec["widgets"][0]["kpi"]["field"] is None
    summed = [
        w["kpi"]["field"] for w in spec["widgets"] if w["kind"] == "kpi" and w["kpi"]["field"]
    ]
    assert "order_id" not in summed and "revenue" in summed


def test_fallback_spec_degenerate_dataset_still_has_kpi_and_table():
    df = pd.DataFrame({"notes": [f"free text number {i} " * 6 for i in range(50)]})
    spec = fallback_spec(profile_dataframe(df), "x")
    kinds = [w["kind"] for w in spec["widgets"]]
    assert "kpi" in kinds and "table" in kinds
