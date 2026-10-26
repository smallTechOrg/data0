"""Offline unit tests for the dashboard aggregation engine (C40, Phase 15).

Every op is checked against a pandas oracle on a >=1,000-row fixture. KPI values
are asserted to equal the FULL-frame result AND to differ from the same op on
`df.head(50)`, so a sampled computation cannot pass.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from graph.dashboard_data import apply_filters, compute_widget, compute_widget_data


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 1200
    out = pd.DataFrame(
        {
            "order_date": pd.date_range("2023-01-01", periods=n, freq="D"),
            "region": rng.choice(["North", "South", "East", "West", "Central"], n),
            "category": rng.choice(["A", "B", "C"], n),
            "customer_id": [f"C-{i % 100:03d}" for i in range(n)],
            "units": rng.integers(1, 30, n),
            "revenue": rng.gamma(2.0, 50.0, n).round(2),
            "discount": np.where(rng.random(n) < 0.2, np.nan, rng.random(n).round(3)),
        }
    )
    # make head(50) clearly different from the full frame
    out.loc[:49, "revenue"] = 1.0
    out.loc[:49, "region"] = "North"
    return out


def _kpi(field, agg, **kw):
    return {"id": "k", "kind": "kpi", "title": "T", "filters": kw.pop("filters", []),
            "kpi": {"field": field, "agg": agg, "format": kw.pop("format", "number")}}


def _chart(**cfg):
    filters = cfg.pop("filters", [])
    return {"id": "c", "kind": "chart", "title": "T", "filters": filters, "chart": cfg}


def _table(**cfg):
    filters = cfg.pop("filters", [])
    return {"id": "t", "kind": "table", "title": "T", "filters": filters, "table": cfg}


@pytest.mark.parametrize(
    "field,agg",
    [
        ("revenue", "sum"),
        ("revenue", "mean"),
        ("revenue", "median"),
        ("revenue", "min"),
        ("revenue", "max"),
        ("revenue", "count"),
        ("discount", "count"),  # nulls excluded
        ("region", "nunique"),
        ("customer_id", "nunique"),
        ("units", "sum"),
    ],
)
def test_kpi_equals_full_frame_oracle_not_sample(df, field, agg):
    out = compute_widget(df, _kpi(field, agg))
    assert out["status"] == "ok", out
    oracle = getattr(df[field], agg)()
    assert math.isclose(out["value"], float(oracle), rel_tol=1e-9, abs_tol=1e-9)
    sampled = getattr(df.head(50)[field], agg)()
    if agg not in ("min",) and not (agg == "count" and field == "revenue") and not (
        agg == "nunique" and field == "region"
    ):
        assert not math.isclose(out["value"], float(sampled), rel_tol=1e-9), "sampled value would pass"


def test_row_count_kpi_and_empty_filter(df):
    out = compute_widget(df, _kpi(None, "count"))
    assert out["value"] == len(df) and out["formatted"] == "1,200"
    out = compute_widget(df, _kpi("revenue", "sum", filters=[{"field": "units", "op": "gt", "value": 10_000}]))
    assert out["status"] == "ok" and out["value"] is None and out["formatted"] == "—"


def test_kpi_datetime_min_max(df):
    out = compute_widget(df, _kpi("order_date", "max"))
    assert out["status"] == "ok"
    assert out["value"].startswith(str(df["order_date"].max().date()))


def test_kpi_on_date_like_text_column():
    d = pd.DataFrame({"d": ["2024-01-05", "2024-03-09", "2023-12-31"]})
    out = compute_widget(d, _kpi("d", "min"))
    assert out["status"] == "ok" and out["value"].startswith("2023-12-31")


def test_kpi_formats(df):
    cur = compute_widget(df, _kpi("revenue", "sum", format="currency"))
    assert cur["formatted"].startswith("$") and "," in cur["formatted"]
    integ = compute_widget(df, _kpi("units", "mean", format="integer"))
    assert "." not in integ["formatted"]


def test_filters_all_ops(df):
    assert len(apply_filters(df, [{"field": "region", "op": "eq", "value": "North"}])) == (df["region"] == "North").sum()
    assert len(apply_filters(df, [{"field": "region", "op": "ne", "value": "North"}])) == (df["region"] != "North").sum()
    assert len(apply_filters(df, [{"field": "units", "op": "gt", "value": 20}])) == (df["units"] > 20).sum()
    assert len(apply_filters(df, [{"field": "units", "op": "gte", "value": 20}])) == (df["units"] >= 20).sum()
    assert len(apply_filters(df, [{"field": "units", "op": "lt", "value": 5}])) == (df["units"] < 5).sum()
    assert len(apply_filters(df, [{"field": "units", "op": "lte", "value": 5}])) == (df["units"] <= 5).sum()
    assert len(apply_filters(df, [{"field": "region", "op": "in", "value": ["North", "East"]}])) == df["region"].isin(["North", "East"]).sum()
    assert len(apply_filters(df, [{"field": "discount", "op": "not_null"}])) == df["discount"].notna().sum()
    got = apply_filters(df, [{"field": "order_date", "op": "gte", "value": "2024-01-01"}])
    assert len(got) == (df["order_date"] >= "2024-01-01").sum()
    both = apply_filters(df, [{"field": "region", "op": "eq", "value": "East"}, {"field": "units", "op": "gt", "value": 15}])
    assert len(both) == ((df["region"] == "East") & (df["units"] > 15)).sum()


def test_filter_with_uncoercible_value_isolated_error(df):
    out = compute_widget(df, _kpi("revenue", "sum", filters=[{"field": "units", "op": "gt", "value": "lots"}]))
    assert out["status"] == "error" and out["message"]


def test_bar_chart_groupby_matches_oracle_and_has_series(df):
    w = _chart(type="bar", x="region", y={"field": "revenue", "agg": "sum"}, sort="y_desc", limit=10)
    out = compute_widget(df, w)
    assert out["status"] == "ok" and "series" in out["option"]
    oracle = df.groupby("region")["revenue"].sum().sort_values(ascending=False)
    assert out["option"]["xAxis"]["data"] == list(oracle.index)
    assert out["option"]["series"][0]["data"] == pytest.approx(list(oracle.values))
    json.dumps(out["option"])  # JSON-safe


def test_bar_limit_and_row_count_y(df):
    w = _chart(type="bar", x="customer_id", y={"field": None, "agg": "count"}, sort="y_desc", limit=7)
    out = compute_widget(df, w)
    assert len(out["option"]["xAxis"]["data"]) == 7
    assert out["option"]["series"][0]["data"][0] == df.groupby("customer_id").size().max()


def test_series_by_top8_plus_other(df):
    d = df.copy()
    d["tag"] = [f"t{i % 12}" for i in range(len(d))]
    w = _chart(type="bar", x="region", y={"field": "revenue", "agg": "sum"}, series_by="tag", limit=10)
    out = compute_widget(d, w)
    assert out["status"] == "ok"
    names = [s["name"] for s in out["option"]["series"]]
    assert len(names) == 9 and "Other" in names
    total = sum(v for s in out["option"]["series"] for v in s["data"] if v is not None)
    assert total == pytest.approx(d["revenue"].sum())


def test_line_monthly_grain_buckets_correctly(df):
    w = _chart(type="line", x="order_date", y={"field": "revenue", "agg": "sum"}, time_grain="month", sort="x_asc", limit=50)
    out = compute_widget(df, w)
    assert out["status"] == "ok"
    oracle = df.groupby(df["order_date"].dt.to_period("M"))["revenue"].sum()
    labels = out["option"]["xAxis"]["data"]
    assert labels == [str(p) for p in oracle.index][-len(labels):]
    assert out["option"]["series"][0]["data"] == pytest.approx(list(oracle.values)[-len(labels):])
    assert out["option"]["series"][0]["type"] == "line"


def test_line_auto_grain_and_date_like_text_x():
    d = pd.DataFrame(
        {"day": pd.date_range("2024-01-01", periods=400, freq="D").strftime("%Y-%m-%d"), "v": 1.0}
    )
    out = compute_widget(d, _chart(type="line", x="day", y={"field": "v", "agg": "sum"}))
    assert out["status"] == "ok"
    labels = out["option"]["xAxis"]["data"]
    assert len(labels) == 14 and labels[0] == "2024-01"  # 400 days -> monthly buckets


def test_quarter_and_year_grains(df):
    q = compute_widget(df, _chart(type="bar", x="order_date", y={"field": "revenue", "agg": "sum"}, time_grain="quarter", sort="x_asc"))
    assert q["option"]["xAxis"]["data"][0] == "2023-Q1"
    y = compute_widget(df, _chart(type="area", x="order_date", y={"field": "units", "agg": "sum"}, time_grain="year"))
    assert y["option"]["xAxis"]["data"] == ["2023", "2024", "2025", "2026"][: len(y["option"]["xAxis"]["data"])]
    assert "areaStyle" in y["option"]["series"][0]


def test_pie_scatter_histogram(df):
    pie = compute_widget(df, _chart(type="pie", x="category", y={"field": "revenue", "agg": "sum"}))
    assert pie["status"] == "ok" and pie["option"]["series"][0]["type"] == "pie"
    assert sum(d["value"] for d in pie["option"]["series"][0]["data"]) == pytest.approx(df["revenue"].sum())
    sc = compute_widget(df, _chart(type="scatter", x="units", y={"field": "revenue", "agg": "none"}))
    assert sc["status"] == "ok" and len(sc["option"]["series"][0]["data"]) <= 2000
    hist = compute_widget(df, _chart(type="histogram", x="revenue", bins=12))
    assert hist["status"] == "ok"
    assert sum(hist["option"]["series"][0]["data"]) == len(df)  # bins sum to row count
    assert len(hist["option"]["xAxis"]["data"]) == 12


def test_chart_with_filter_and_empty_filter_error(df):
    w = _chart(type="bar", x="region", y={"field": "revenue", "agg": "sum"},
               filters=[{"field": "category", "op": "eq", "value": "A"}])
    out = compute_widget(df, w)
    oracle = df[df["category"] == "A"].groupby("region")["revenue"].sum()
    assert sorted(out["option"]["series"][0]["data"]) == pytest.approx(sorted(oracle.values))
    empty = _chart(type="bar", x="region", y={"field": "revenue", "agg": "sum"},
                   filters=[{"field": "category", "op": "eq", "value": "ZZZ"}])
    assert compute_widget(df, empty)["status"] == "error"


def test_table_grouped_matches_oracle(df):
    w = _table(group_by=["customer_id"], aggs=[{"field": "revenue", "agg": "sum", "alias": "revenue"}],
               sort_by="revenue", sort_dir="desc", limit=10)
    out = compute_widget(df, w)
    assert out["status"] == "ok" and out["columns"] == ["customer_id", "revenue"]
    oracle = df.groupby("customer_id")["revenue"].sum().sort_values(ascending=False).head(10)
    assert [r[0] for r in out["rows"]] == list(oracle.index)
    assert [r[1] for r in out["rows"]] == pytest.approx([round(v, 4) for v in oracle.values])
    assert out["truncated"] is True and len(out["rows"]) == 10


def test_table_grouped_multi_agg_and_default_sort(df):
    w = _table(group_by=["region", "category"],
               aggs=[{"field": None, "agg": "count"}, {"field": "units", "agg": "mean", "alias": "avg_units"}],
               limit=50)
    out = compute_widget(df, w)
    assert out["columns"] == ["region", "category", "count", "avg_units"]
    counts = [r[2] for r in out["rows"]]
    assert counts == sorted(counts, reverse=True)
    assert sum(counts) == len(df)


def test_table_raw_mode_sort_limit_and_formatting(df):
    w = _table(columns=["customer_id", "revenue", "discount", "order_date"], sort_by="revenue", sort_dir="desc", limit=5)
    out = compute_widget(df, w)
    assert out["status"] == "ok" and len(out["rows"]) == 5 and out["truncated"] is True
    assert out["rows"][0][1] == pytest.approx(df["revenue"].max())
    json.dumps(out)  # NaN/Timestamp safe
    assert isinstance(out["rows"][0][3], str)
    nan_rows = compute_widget(df, _table(columns=["discount"], limit=50))
    assert any(r[0] is None for r in nan_rows["rows"])


def test_removed_column_isolates_to_that_widget(df):
    spec = {
        "widgets": [
            {**_kpi("revenue", "sum"), "id": "a"},
            {**_kpi("discount", "mean"), "id": "b"},
            {**_chart(type="bar", x="region", y={"field": "revenue", "agg": "sum"}), "id": "c"},
        ]
    }
    data = compute_widget_data(df.drop(columns=["discount"]), spec)
    assert data["a"]["status"] == "ok" and data["c"]["status"] == "ok"
    assert data["b"]["status"] == "error" and "discount" in data["b"]["message"]
    assert "no longer exists" in data["b"]["message"]


def test_whole_payload_is_json_safe(df):
    spec = {
        "widgets": [
            {**_kpi("discount", "mean"), "id": "a"},
            {**_chart(type="line", x="order_date", y={"field": "discount", "agg": "mean"}, time_grain="month"), "id": "b"},
            {**_table(columns=["order_date", "discount"], limit=50), "id": "c"},
        ]
    }
    data = compute_widget_data(df, spec)
    text = json.dumps(data, allow_nan=False)
    assert "NaN" not in text


def test_all_null_numeric_does_not_crash():
    d = pd.DataFrame({"a": [np.nan, np.nan], "b": ["x", "y"]})
    out = compute_widget(d, _kpi("a", "sum"))
    assert out["status"] == "ok"
    json.dumps(out, allow_nan=False)
