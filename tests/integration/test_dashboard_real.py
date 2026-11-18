"""Real-Gemini integration test for the Phase-15 agent-built dashboard (C40).

SCOPED: exactly ONE build (<= 2 LLM calls) — the Gemini key is free-tier
constrained. Requires a real LLM key in `.env` (skipped otherwise). Drives the
full path through the `api_client` TestClient: `POST /upload` a 600-row engineered
orders CSV, `POST /datasets/{id}/dashboards` with a real natural-language command,
then asserts the spec is valid against the REAL columns, KPI sums equal the
full-data pandas sum, every widget computes `ok`, and a permuted layout persists.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from graph.dashboard import validate_layout, validate_spec
from graph.dashboard_profile import columns_schema_for

COMMAND = (
    "Build a sales dashboard: total revenue and total units, revenue by region, "
    "a monthly revenue trend, and a table of the top 10 customers by revenue"
)


def _orders_df(n: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(2026)
    return pd.DataFrame(
        {
            "order_id": [f"O-{i:05d}" for i in range(n)],
            "order_date": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
            "region": rng.choice(["North", "South", "East", "West", "Central"], n),
            "category": rng.choice(["Hardware", "Software", "Services"], n),
            "customer_id": [f"CUST-{i % 60:03d}" for i in range(n)],
            "units": rng.integers(1, 25, n),
            "revenue": rng.gamma(2.0, 80.0, n).round(2),
        }
    )


def _referenced_fields(widget: dict) -> set[str]:
    fields = {f["field"] for f in widget.get("filters") or []}
    kind = widget["kind"]
    if kind == "kpi":
        fields.add(widget["kpi"]["field"])
    elif kind == "chart":
        c = widget["chart"]
        fields |= {c["x"], c.get("series_by"), (c.get("y") or {}).get("field")}
    else:
        t = widget["table"]
        fields |= set(t.get("columns") or []) | set(t.get("group_by") or [])
        fields |= {a.get("field") for a in t.get("aggs") or []}
    fields.discard(None)
    return fields


@pytest.mark.usefixtures("_require_llm_key")
def test_real_gemini_builds_valid_dashboard(api_client, tmp_path, monkeypatch):
    # Keep the real uploads/ dir clean: write/read dataset files in a temp dir.
    import api.upload as upload_module
    import graph.nodes as nodes

    uploads = tmp_path / "uploads"
    monkeypatch.setattr(upload_module, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(nodes, "_uploads_dir", lambda: uploads)
    # Don't spend an extra real LLM call on the C30 auto-notes job.
    monkeypatch.setattr(upload_module, "trigger_describe_async", lambda _id: None)

    df = _orders_df()
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    up = api_client.post("/upload?force=true", files={"file": ("orders.csv", buf, "text/csv")})
    assert up.status_code == 200, up.text
    dataset_id = up.json()["data"]["dataset_id"]

    r = api_client.post(f"/datasets/{dataset_id}/dashboards", json={"command": COMMAND})
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    dash, data = body["dashboard"], body["data"]
    spec, gen = dash["spec"], dash["generation"]

    # The real model must actually deliver usable JSON (not the automatic fallback).
    assert gen["used_fallback"] is False, gen
    assert "[stub]" not in str(spec)

    # Spec re-passes validation and references only real columns.
    schema = columns_schema_for(df)
    clean, errors = validate_spec(spec, schema)
    assert errors == [] and len(clean) == len(spec["widgets"])
    kinds = [w["kind"] for w in spec["widgets"]]
    assert "kpi" in kinds and "chart" in kinds and "table" in kinds, kinds
    for w in spec["widgets"]:
        assert _referenced_fields(w) <= set(df.columns), (w["title"], _referenced_fields(w))

    # Every widget computed; each chart option has a series.
    assert set(data["widgets"]) == {w["id"] for w in spec["widgets"]}
    for w in spec["widgets"]:
        out = data["widgets"][w["id"]]
        assert out["status"] == "ok", (w["title"], out)
        if w["kind"] == "chart":
            assert "series" in out["option"]

    # A revenue-sum KPI equals the FULL-data pandas sum (not a sampled one).
    revenue_kpis = [
        w for w in spec["widgets"]
        if w["kind"] == "kpi" and w["kpi"]["agg"] == "sum" and w["kpi"]["field"] == "revenue"
        and not w["filters"]
    ]
    assert revenue_kpis, "expected a total-revenue KPI"
    got = data["widgets"][revenue_kpis[0]["id"]]["value"]
    assert abs(got - df["revenue"].sum()) < 1e-6
    assert abs(got - df.head(50)["revenue"].sum()) > 1.0  # a sampled sum would differ

    # Layout: server-assigned layout is valid; a permuted valid layout persists.
    ids = [w["id"] for w in spec["widgets"]]
    current = [{"id": w["id"], **w["layout"]} for w in spec["widgets"]]
    assert validate_layout(current, ids)[1] is None
    permuted = list(reversed(spec["widgets"]))
    # re-pack the reversed order top-to-bottom, full width each (always valid)
    y, new_layout = 0, []
    for w in permuted:
        h = w["layout"]["h"]
        new_layout.append({"id": w["id"], "x": 0, "y": y, "w": 12, "h": h})
        y += h
    assert validate_layout(new_layout, ids)[1] is None
    pr = api_client.patch(f"/dashboards/{dash['id']}", json={"layout": new_layout})
    assert pr.status_code == 200, pr.text
    again = api_client.get(f"/dashboards/{dash['id']}").json()["data"]
    stored = {w["id"]: w["layout"] for w in again["spec"]["widgets"]}
    assert stored == {e["id"]: {k: e[k] for k in "xywh"} for e in new_layout}
