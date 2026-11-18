"""Real-LLM gate for priority-ranked insights (C41, Phase 16).

SCOPED: one build (<= 2 LLM calls); reuses the Phase 15 fixture builder. Asserts
the agent ranks and describes every widget and justifies every chart, that its
chart choices obey the rules, that the numbers are full-data, that its text does
not assert findings it cannot know, and that reordering priority makes no LLM call.
"""
from __future__ import annotations

import io
import re

import pytest

from graph.dashboard_charts import find_column
from graph.dashboard_profile import profile_dataframe
from test_dashboard_real import _orders_df

COMMAND = (
    "Build an executive sales dashboard: total revenue, units, revenue by region, "
    "monthly trend, top customers — most important first"
)
# Result-claiming phrasing the agent cannot back: it writes text before numbers exist.
_FINDING = re.compile(
    r"\b(is|are|has been|have been) (growing|declining|rising|falling|increasing|decreasing)\b"
    r"|\btrends? (up|down)\b|\b(north|south|east|west|central) (leads|is the top)\b",
    re.IGNORECASE,
)


@pytest.mark.usefixtures("_require_llm_key")
def test_real_llm_ranks_and_describes_dashboard(api_client, tmp_path, monkeypatch):
    import api.upload as upload_module
    import graph.dashboard as dash_module
    import graph.nodes as nodes

    uploads = tmp_path / "uploads"
    monkeypatch.setattr(upload_module, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(nodes, "_uploads_dir", lambda: uploads)
    monkeypatch.setattr(upload_module, "trigger_describe_async", lambda _id: None)

    calls = {"n": 0}
    real_client = dash_module.LLMClient

    class Counting(real_client):
        def complete(self, *args, **kwargs):
            calls["n"] += 1
            return super().complete(*args, **kwargs)

    monkeypatch.setattr(dash_module, "LLMClient", Counting)

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
    widgets = spec["widgets"]
    build_calls = calls["n"]

    assert gen["used_fallback"] is False, gen
    assert 1 <= build_calls <= 2
    assert spec["version"] == 2 and spec["summary"]

    # Ranked and described, by the agent.
    assert sorted(w["priority"] for w in widgets) == list(range(1, len(widgets) + 1))
    for w in widgets:
        assert w["description"] and len(w["description"]) <= 200, w
        assert w["description_source"] == "agent", w
        if w["kind"] == "chart":
            assert w["chart_rationale"] and len(w["chart_rationale"]) <= 140, w
    for text in [spec["summary"], *(w["description"] for w in widgets)]:
        assert not _FINDING.search(text), text

    # Chart choices obey the rules.
    profile = profile_dataframe(df)
    charts = [w for w in widgets if w["kind"] == "chart"]
    trends = [w for w in charts if w["chart"]["x"] == "order_date"]
    assert trends, "expected a monthly trend chart"
    assert all(w["chart"]["type"] in ("line", "area") for w in trends)
    for w in charts:
        if w["chart"]["type"] == "pie":
            assert int(find_column(profile, w["chart"]["x"])["nunique"]) <= 8, w

    # Insights: KPI-only, in priority order, showing the full-data numbers.
    kpis = sorted((w for w in widgets if w["kind"] == "kpi"), key=lambda w: w["priority"])
    insights = data["insights"]
    assert insights and [i["widget_id"] for i in insights] == [w["id"] for w in kpis][:6]
    revenue = next(
        w for w in kpis if w["kpi"]["agg"] == "sum" and w["kpi"]["field"] == "revenue" and not w["filters"]
    )
    computed = data["widgets"][revenue["id"]]
    assert abs(computed["value"] - df["revenue"].sum()) < 1e-6
    assert next(i for i in insights if i["widget_id"] == revenue["id"])["headline"] == computed["formatted"]

    # Reading order: the top-ranked KPI sits top-left.
    at_origin = next(w for w in widgets if (w["layout"]["x"], w["layout"]["y"]) == (0, 0))
    assert at_origin["id"] == kpis[0]["id"]

    # Reversing priority re-ranks and persists with no LLM call.
    reversed_order = [w["id"] for w in sorted(widgets, key=lambda w: -w["priority"])]
    pr = api_client.patch(f"/dashboards/{dash['id']}", json={"priority_order": reversed_order})
    assert pr.status_code == 200, pr.text
    again = api_client.get(f"/dashboards/{dash['id']}").json()["data"]["spec"]["widgets"]
    assert [w["id"] for w in sorted(again, key=lambda w: w["priority"])] == reversed_order
    assert calls["n"] == build_calls
