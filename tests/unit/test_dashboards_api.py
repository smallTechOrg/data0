"""Offline unit tests for the Phase-15 dashboard routes + build pipeline (C40).

Stub provider by default (-> deterministic fallback); the LLM-path tests inject a
fake `LLMClient` (monkeypatch) with canned replies and count the calls. Isolated
SQLite via the conftest `_isolated_db`; zero network.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session as OrmSession


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    import config.settings as m

    m._settings = None


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    import graph.nodes as nodes

    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes, "_uploads_dir", lambda: d)
    return d


@pytest.fixture
def make_dataset(uploads):
    from db.models import DatasetRow
    from db.session import create_db_session

    def _make(df: pd.DataFrame, filename: str = "sales.csv", facts=None) -> str:
        with create_db_session() as s:
            row = DatasetRow(
                filename=filename,
                file_path="",
                row_count=len(df),
                col_count=len(df.columns),
                columns_json=[{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
                content_hash=f"h-{filename}",
                format="csv",
                origin="uploaded",
                context_facts=facts,
            )
            s.add(row)
            s.flush()
            did = row.id
        df.to_csv(uploads / f"{did}.csv", index=False)
        return did

    return _make


def _sales_df(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "order_id": np.arange(n),
            "order_date": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
            "region": rng.choice(["N", "S", "E", "W"], n),
            "customer_id": [f"C-{i % 30:02d}" for i in range(n)],
            "units": rng.integers(1, 20, n),
            "revenue": rng.gamma(2, 50, n).round(2),
        }
    )


@pytest.fixture
def dataset_id(make_dataset):
    return make_dataset(_sales_df())


GOOD = {
    "title": "Sales overview",
    "description": "Revenue by region",
    "widgets": [
        {"id": "w1", "kind": "kpi", "title": "Total revenue",
         "kpi": {"field": "revenue", "agg": "sum", "format": "currency"}},
        {"id": "w2", "kind": "chart", "title": "Revenue by region",
         "chart": {"type": "bar", "x": "region", "y": {"field": "revenue", "agg": "sum"}}},
        {"id": "w3", "kind": "table", "title": "Top customers",
         "table": {"group_by": ["customer_id"],
                   "aggs": [{"field": "revenue", "agg": "sum", "alias": "revenue"}],
                   "sort_by": "revenue", "limit": 10}},
    ],
}


def _fake_llm(monkeypatch, replies, raises=None):
    """Patch `graph.dashboard.LLMClient` with canned replies; returns the call log."""
    import graph.dashboard as dash

    calls: list[str] = []
    queue = list(replies)

    class Fake:
        provider = "fake"
        model = "fake-model"

        def complete(self, prompt, *, system=None):
            calls.append(prompt)
            if raises is not None:
                raise raises
            text = queue.pop(0) if queue else ""
            return SimpleNamespace(text=text, tokens_input=100, tokens_output=50)

    monkeypatch.setattr(dash, "LLMClient", Fake)
    return calls


def _create(client, dataset_id, command="show revenue by region", **extra):
    return client.post(f"/datasets/{dataset_id}/dashboards", json={"command": command, **extra})


def _kinds(spec):
    return [w["kind"] for w in spec["widgets"]]


def _widget(spec, kind):
    return next(w for w in spec["widgets"] if w["kind"] == kind)


# --- create: LLM paths -------------------------------------------------------


def test_good_json_persists_and_returns_data(api_client, dataset_id, monkeypatch):
    calls = _fake_llm(monkeypatch, [json.dumps(GOOD)])
    r = _create(api_client, dataset_id)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    dash, data = body["dashboard"], body["data"]
    assert len(calls) == 1
    gen = dash["generation"]
    assert gen["used_fallback"] is False and gen["repaired"] is False
    assert gen["supplemented"] == [] and gen["dropped_widgets"] == []
    assert gen["tokens_input"] == 100 and gen["model"] == "fake-model"
    assert dash["title"] == "Sales overview" and dash["dataset_filename"] == "sales.csv"
    assert _kinds(dash["spec"]) == ["kpi", "chart", "table"]
    assert all("layout" in w for w in dash["spec"]["widgets"])
    assert set(data["widgets"]) == {"w1", "w2", "w3"}
    assert all(w["status"] == "ok" for w in data["widgets"].values())
    assert "series" in data["widgets"]["w2"]["option"]
    assert data["row_count"] == 300
    # persisted
    got = api_client.get(f"/dashboards/{dash['id']}").json()["data"]
    assert got["spec"] == dash["spec"]


def test_kpi_value_is_full_data_sum(api_client, make_dataset, monkeypatch):
    df = _sales_df(900)
    did = make_dataset(df)
    _fake_llm(monkeypatch, [json.dumps(GOOD)])
    data = _create(api_client, did).json()["data"]["data"]
    assert data["widgets"]["w1"]["value"] == pytest.approx(df["revenue"].sum())


def test_fenced_json_and_prose_wrapped_json(api_client, dataset_id, monkeypatch):
    _fake_llm(monkeypatch, ["Here you go:\n```json\n" + json.dumps(GOOD) + "\n```\nEnjoy!"])
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    assert d["generation"]["used_fallback"] is False
    _fake_llm(monkeypatch, ["Sure! " + json.dumps(GOOD) + " Hope that helps."])
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    assert d["generation"]["used_fallback"] is False


def test_unknown_column_repaired_once_then_succeeds(api_client, dataset_id, monkeypatch):
    bad = json.loads(json.dumps(GOOD))
    bad["widgets"][0]["kpi"]["field"] = "profit"
    calls = _fake_llm(monkeypatch, [json.dumps(bad), json.dumps(GOOD)])
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    assert len(calls) == 2  # exactly one repair call
    assert "unknown_field" in calls[1] and "Validation errors" in calls[1]
    gen = d["generation"]
    assert gen["repaired"] is True and gen["used_fallback"] is False
    assert gen["dropped_widgets"] == []
    assert gen["tokens_input"] == 200
    assert _widget(d["spec"], "kpi")["kpi"]["field"] == "revenue"


def test_repair_still_bad_drops_offending_widget(api_client, dataset_id, monkeypatch):
    bad = json.loads(json.dumps(GOOD))
    bad["widgets"][2]["table"]["group_by"] = ["nonexistent"]
    calls = _fake_llm(monkeypatch, [json.dumps(bad), json.dumps(bad)])
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    assert len(calls) == 2
    gen = d["generation"]
    assert gen["used_fallback"] is False
    assert [w["title"] for w in gen["dropped_widgets"]] == ["Top customers"]
    assert gen["dropped_widgets"][0]["reason"].startswith("unknown_field")
    assert _kinds(d["spec"]) == ["kpi", "chart"]
    # the delivered spec never contains an unknown field
    cols = set(_sales_df().columns)
    for w in d["spec"]["widgets"]:
        assert {w["kpi"]["field"]} - {None} <= cols if w["kind"] == "kpi" else True


@pytest.mark.parametrize(
    "reply",
    ["", "I cannot do that.", "[1, 2, 3]", '{"title": "x"}', '{"widgets": []}', '{"widgets": [{"kind": "kpi"}]}'],
)
def test_unusable_replies_fall_back_never_5xx(api_client, dataset_id, monkeypatch, reply):
    _fake_llm(monkeypatch, [reply, reply])
    r = _create(api_client, dataset_id)
    assert r.status_code == 200, r.text
    d = r.json()["data"]["dashboard"]
    assert d["generation"]["used_fallback"] is True
    kinds = _kinds(d["spec"])
    assert "kpi" in kinds and "chart" in kinds
    assert d["title"]


def test_llm_raises_falls_back_with_note(api_client, dataset_id, monkeypatch):
    calls = _fake_llm(monkeypatch, [], raises=RuntimeError("429 rate limited"))
    r = _create(api_client, dataset_id)
    assert r.status_code == 200
    gen = r.json()["data"]["dashboard"]["generation"]
    assert gen["used_fallback"] is True
    assert any("LLM unavailable: RuntimeError" in n for n in gen["notes"])
    assert len(calls) == 1  # no repair after an exception


def test_stub_provider_yields_fallback_dashboard(api_client, dataset_id):
    r = _create(api_client, dataset_id)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    gen = body["dashboard"]["generation"]
    assert gen["used_fallback"] is True
    kinds = _kinds(body["dashboard"]["spec"])
    assert "kpi" in kinds and "chart" in kinds and "table" in kinds
    assert all(w["status"] == "ok" for w in body["data"]["widgets"].values())


def test_missing_kpi_and_chart_supplemented(api_client, dataset_id, monkeypatch):
    only_table = {"title": "Customers", "widgets": [GOOD["widgets"][2]]}
    _fake_llm(monkeypatch, [json.dumps(only_table)])
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    gen = d["generation"]
    assert gen["used_fallback"] is False
    assert sorted(gen["supplemented"]) == ["chart", "kpi"]
    kinds = _kinds(d["spec"])
    assert "kpi" in kinds and "chart" in kinds and "table" in kinds
    ids = [w["id"] for w in d["spec"]["widgets"]]
    assert len(ids) == len(set(ids))


def test_user_title_wins_and_prompt_has_command_and_notes(api_client, make_dataset, monkeypatch):
    did = make_dataset(_sales_df(), facts=["revenue is in USD", "region is the sales territory"])
    calls = _fake_llm(monkeypatch, [json.dumps(GOOD)])
    d = _create(api_client, did, command="make it pretty", title="  My board ").json()["data"]["dashboard"]
    assert d["title"] == "My board" and d["spec"]["title"] == "My board"
    assert "<node:dashboard>" in calls[0] and "make it pretty" in calls[0]
    assert "revenue is in USD" in calls[0]
    assert "order_id" in calls[0]  # profile column names are sent


def test_prompt_never_contains_full_data(api_client, make_dataset, monkeypatch):
    df = _sales_df(400)
    df["secret_note"] = [f"UNIQUE-TOKEN-{i}" for i in range(400)]
    did = make_dataset(df)
    calls = _fake_llm(monkeypatch, [json.dumps(GOOD)])
    _create(api_client, did)
    present = sum(f"UNIQUE-TOKEN-{i}" in calls[0] for i in range(400))
    assert present <= 5  # only the <=5 sample rows


# --- create: errors ----------------------------------------------------------


def test_create_error_codes(api_client, dataset_id, make_dataset):
    r = _create(api_client, "nope")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "dataset_not_found"
    for cmd in ("", "   "):
        r = _create(api_client, dataset_id, command=cmd)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "empty_command"
    r = api_client.post(f"/datasets/{dataset_id}/dashboards", json={})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "empty_command"
    r = _create(api_client, dataset_id, command="x" * 1001)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "command_too_long"
    empty = make_dataset(pd.DataFrame({"a": pd.Series([], dtype=float)}), filename="empty.csv")
    r = _create(api_client, empty)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "empty_dataset"


def test_unreadable_dataset_file_is_dashboard_failed_and_nothing_persisted(
    api_client, dataset_id, uploads
):
    (uploads / f"{dataset_id}.csv").unlink()
    r = _create(api_client, dataset_id)
    assert r.status_code == 500 and r.json()["detail"]["code"] == "dashboard_failed"
    assert api_client.get("/dashboards").json()["data"] == []


def test_commit_failure_is_write_failed_no_phantom_row(api_client, dataset_id, monkeypatch):
    real_commit = OrmSession.commit

    def boom(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(OrmSession, "commit", boom)
    r = _create(api_client, dataset_id)
    assert r.status_code == 500 and r.json()["detail"]["code"] == "write_failed"
    monkeypatch.setattr(OrmSession, "commit", real_commit)
    assert api_client.get("/dashboards").json()["data"] == []


# --- get / list / data -------------------------------------------------------


def test_list_get_and_filter_by_dataset(api_client, make_dataset, dataset_id):
    other = make_dataset(_sales_df(50), filename="other.csv")
    a = _create(api_client, dataset_id, title="A").json()["data"]["dashboard"]
    b = _create(api_client, other, title="B").json()["data"]["dashboard"]
    items = api_client.get("/dashboards").json()["data"]
    assert [i["title"] for i in items] == ["B", "A"]  # most recently updated first
    assert {"id", "dataset_id", "dataset_filename", "title", "command", "widget_count",
            "used_fallback", "created_at", "updated_at"} <= set(items[0])
    assert items[0]["used_fallback"] is True and items[0]["widget_count"] >= 3
    only_a = api_client.get("/dashboards", params={"dataset_id": dataset_id}).json()["data"]
    assert [i["id"] for i in only_a] == [a["id"]]
    assert api_client.get(f"/dashboards/{b['id']}").json()["data"]["dataset_filename"] == "other.csv"
    r = api_client.get("/dashboards/missing")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "dashboard_not_found"


def test_data_endpoint_recomputes_fresh_and_isolates_removed_column(
    api_client, dataset_id, uploads, monkeypatch
):
    _fake_llm(monkeypatch, [json.dumps(GOOD)])
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    first = api_client.get(f"/dashboards/{d['id']}/data").json()["data"]
    assert first["dashboard_id"] == d["id"] and first["dataset_id"] == dataset_id
    assert first["widgets"]["w2"]["status"] == "ok" and "series" in first["widgets"]["w2"]["option"]

    # dataset changes (a column disappears, rows change) -> next open reflects it
    new = _sales_df(120).drop(columns=["region"])
    new.to_csv(uploads / f"{dataset_id}.csv", index=False)
    second = api_client.get(f"/dashboards/{d['id']}/data").json()["data"]
    assert second["row_count"] == 120
    assert second["widgets"]["w1"]["status"] == "ok"
    assert second["widgets"]["w1"]["value"] == pytest.approx(new["revenue"].sum())
    assert second["widgets"]["w2"]["status"] == "error"
    assert "region" in second["widgets"]["w2"]["message"]
    assert second["widgets"]["w3"]["status"] == "ok"


def test_data_endpoint_errors(api_client, dataset_id, uploads):
    r = api_client.get("/dashboards/missing/data")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "dashboard_not_found"
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    (uploads / f"{dataset_id}.csv").unlink()
    r = api_client.get(f"/dashboards/{d['id']}/data")
    assert r.status_code == 500 and r.json()["detail"]["code"] == "dashboard_failed"


def test_data_endpoint_dataset_row_gone_is_404(api_client, dataset_id, _isolated_db):
    from sqlalchemy.orm import sessionmaker
    from db.models import DatasetRow

    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    S = sessionmaker(bind=_isolated_db)
    with S() as s:  # remove only the dataset row (bypass the cascade)
        s.delete(s.get(DatasetRow, dataset_id))
        s.commit()
    r = api_client.get(f"/dashboards/{d['id']}/data")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "dataset_not_found"


# --- patch -------------------------------------------------------------------


def _layout_of(d):
    return {w["id"]: w["layout"] for w in d["spec"]["widgets"]}


def test_patch_valid_permutation_persists(api_client, dataset_id):
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    widgets = d["spec"]["widgets"]
    # swap the positions of the first two widgets (same size KPIs) and keep others
    lay = [{"id": w["id"], **w["layout"]} for w in widgets]
    a, b = lay[0], lay[1]
    a_pos, b_pos = (a["x"], a["y"]), (b["x"], b["y"])
    a["x"], a["y"] = b_pos
    b["x"], b["y"] = a_pos
    r = api_client.patch(f"/dashboards/{d['id']}", json={"layout": lay})
    assert r.status_code == 200, r.text
    again = api_client.get(f"/dashboards/{d['id']}").json()["data"]
    assert _layout_of(again) == {e["id"]: {k: e[k] for k in "xywh"} for e in lay}
    assert again["updated_at"] >= d["updated_at"]


@pytest.mark.parametrize("mutation", ["overlap", "oob", "missing", "unknown", "dup", "float"])
def test_patch_invalid_layout_400_and_unchanged(api_client, dataset_id, mutation):
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    before = _layout_of(d)
    lay = [{"id": w["id"], **w["layout"]} for w in d["spec"]["widgets"]]
    if mutation == "overlap":
        lay[1]["x"], lay[1]["y"] = lay[0]["x"], lay[0]["y"]
    elif mutation == "oob":
        lay[0]["x"] = 11
    elif mutation == "missing":
        lay = lay[:-1]
    elif mutation == "unknown":
        lay[0]["id"] = "ghost"
    elif mutation == "dup":
        lay[1]["id"] = lay[0]["id"]
    elif mutation == "float":
        lay[0]["w"] = 2.5
    r = api_client.patch(f"/dashboards/{d['id']}", json={"layout": lay})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_layout"
    assert _layout_of(api_client.get(f"/dashboards/{d['id']}").json()["data"]) == before


def test_patch_title_empty_patch_and_404(api_client, dataset_id):
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    r = api_client.patch(f"/dashboards/{d['id']}", json={"title": "  Renamed board "})
    assert r.status_code == 200 and r.json()["data"]["title"] == "Renamed board"
    assert r.json()["data"]["spec"]["title"] == "Renamed board"
    assert api_client.get("/dashboards").json()["data"][0]["title"] == "Renamed board"
    for body in ({}, {"other": 1}, []):
        r = api_client.patch(f"/dashboards/{d['id']}", json=body)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "empty_patch"
    for bad in ("", "   ", "x" * 81, 5):
        r = api_client.patch(f"/dashboards/{d['id']}", json={"title": bad})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_title"
    r = api_client.patch("/dashboards/missing", json={"title": "x"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "dashboard_not_found"


def test_patch_title_and_layout_together_and_commit_failure(api_client, dataset_id, monkeypatch):
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    lay = [{"id": w["id"], **w["layout"]} for w in d["spec"]["widgets"]]
    real_commit = OrmSession.commit
    monkeypatch.setattr(OrmSession, "commit", lambda self: (_ for _ in ()).throw(RuntimeError("x")))
    r = api_client.patch(f"/dashboards/{d['id']}", json={"title": "Nope", "layout": lay})
    assert r.status_code == 500 and r.json()["detail"]["code"] == "write_failed"
    monkeypatch.setattr(OrmSession, "commit", real_commit)
    assert api_client.get(f"/dashboards/{d['id']}").json()["data"]["title"] == d["title"]


# --- delete / cascade --------------------------------------------------------


def test_delete_dashboard_leaves_dataset(api_client, dataset_id):
    d = _create(api_client, dataset_id).json()["data"]["dashboard"]
    r = api_client.delete(f"/dashboards/{d['id']}")
    assert r.status_code == 200 and r.json()["data"] == {"deleted": True}
    assert api_client.get(f"/dashboards/{d['id']}").status_code == 404
    assert api_client.get(f"/datasets/{dataset_id}").status_code == 200
    assert api_client.delete(f"/dashboards/{d['id']}").status_code == 404


def test_deleting_dataset_removes_its_dashboards_only(api_client, make_dataset, dataset_id):
    other = make_dataset(_sales_df(60), filename="keep.csv")
    _create(api_client, dataset_id)
    _create(api_client, dataset_id)
    keep = _create(api_client, other).json()["data"]["dashboard"]
    assert api_client.delete(f"/datasets/{dataset_id}").status_code == 200
    remaining = api_client.get("/dashboards").json()["data"]
    assert [i["id"] for i in remaining] == [keep["id"]]


def test_delete_all_datasets_removes_all_dashboards(api_client, make_dataset, dataset_id):
    other = make_dataset(_sales_df(60), filename="two.csv")
    _create(api_client, dataset_id)
    _create(api_client, other)
    assert len(api_client.get("/dashboards").json()["data"]) == 2
    assert api_client.delete("/datasets").status_code == 200
    assert api_client.get("/dashboards").json()["data"] == []


def test_derived_child_dashboards_cascade(api_client, make_dataset, dataset_id, _isolated_db):
    from sqlalchemy.orm import sessionmaker
    from db.models import DatasetRow

    child = make_dataset(_sales_df(40), filename="child.csv")
    S = sessionmaker(bind=_isolated_db)
    with S() as s:
        row = s.get(DatasetRow, child)
        row.origin = "derived"
        row.derived_from_dataset_ids = [dataset_id]
        s.commit()
    _create(api_client, child)
    assert api_client.delete(f"/datasets/{dataset_id}").status_code == 200
    assert api_client.get("/dashboards").json()["data"] == []


# --- migration ---------------------------------------------------------------


def test_migration_creates_dashboards_table(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    import config.settings as m

    m._settings = None
    root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    insp = inspect(engine)
    assert "dashboards" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("dashboards")}
    assert {"id", "dataset_id", "title", "command", "spec_json", "generation_json",
            "tokens_input", "tokens_output", "created_at", "updated_at"} <= cols
    assert any("dataset_id" in ix["column_names"] for ix in insp.get_indexes("dashboards"))
    command.downgrade(cfg, "f7a8b9c0d1e2")
    assert "dashboards" not in inspect(engine).get_table_names()
    engine.dispose()


# --- C41: ranked insights, priority reorder, lazy v1 upgrade ---------------------


RANKED = {
    "title": "Ranked",
    "summary": "  Where   revenue comes from. ",
    "widgets": [
        {"id": "t", "kind": "table", "title": "Top customers", "priority": 2,
         "description": "Customers to look after.", "description_source": "user",
         "table": {"group_by": ["customer_id"],
                   "aggs": [{"field": "revenue", "agg": "sum", "alias": "revenue"}], "limit": 5}},
        {"id": "k2", "kind": "kpi", "title": "Units", "priority": 3,
         "kpi": {"field": "units", "agg": "sum", "format": "integer"}},
        {"id": "k1", "kind": "kpi", "title": "Revenue", "priority": 1,
         "description": "The headline number.",
         "kpi": {"field": "revenue", "agg": "sum", "format": "currency"}},
        {"id": "c", "kind": "chart", "title": "By customer", "priority": 4,
         "chart_rationale": "A pie shows shares.",
         "chart": {"type": "pie", "x": "customer_id", "y": {"field": "revenue", "agg": "sum"}}},
    ],
}


def _build_ranked(api_client, dataset_id, monkeypatch):
    calls = _fake_llm(monkeypatch, [json.dumps(RANKED)])
    r = _create(api_client, dataset_id)
    assert r.status_code == 200, r.text
    return r.json()["data"], calls


def _by_id(spec):
    return {w["id"]: w for w in spec["widgets"]}


def test_ranked_reply_produces_v2_spec_and_insights(api_client, dataset_id, monkeypatch):
    body, calls = _build_ranked(api_client, dataset_id, monkeypatch)
    assert len(calls) == 1  # no extra call for ranking or text
    spec = body["dashboard"]["spec"]
    assert spec["version"] == 2 and spec["summary"] == "Where revenue comes from."
    w = _by_id(spec)
    assert (w["k1"]["layout"]["x"], w["k1"]["layout"]["y"]) == (0, 0)  # priority 1 KPI top-left
    assert w["k1"]["description_source"] == "agent"
    assert w["k2"]["description_source"] == "auto" and w["k2"]["description"]
    assert w["t"]["description_source"] == "agent"  # the LLM cannot claim user authorship
    insights = body["data"]["insights"]
    assert [i["widget_id"] for i in insights] == ["k1", "k2"]
    assert insights[0]["why"] == "The headline number."
    assert insights[0]["headline"] == body["data"]["widgets"]["k1"]["formatted"]
    assert api_client.get(f"/dashboards/{body['dashboard']['id']}/data").json()["data"]["insights"] == insights


def test_pie_over_many_categories_is_clamped_and_noted(api_client, dataset_id, monkeypatch):
    body, _ = _build_ranked(api_client, dataset_id, monkeypatch)
    chart = _by_id(body["dashboard"]["spec"])["c"]
    assert chart["chart"]["type"] == "bar"
    assert chart["chart_rationale"] != "A pie shows shares."
    assert any("customer_id" in n for n in body["dashboard"]["generation"]["notes"])
    assert body["data"]["widgets"]["c"]["status"] == "ok"


def test_fallback_dashboard_is_v2_with_auto_text(api_client, dataset_id):
    body = _create(api_client, dataset_id).json()["data"]  # stub provider -> fallback
    spec = body["dashboard"]["spec"]
    assert body["dashboard"]["generation"]["used_fallback"] is True
    assert spec["version"] == 2 and spec["summary"]
    assert sorted(w["priority"] for w in spec["widgets"]) == list(range(1, len(spec["widgets"]) + 1))
    assert all(w["description_source"] == "auto" for w in spec["widgets"])
    assert all(w["chart_rationale"] for w in spec["widgets"] if w["kind"] == "chart")
    assert body["data"]["insights"][-1]["title"] == "Rows"


def test_patch_priority_order_repacks_in_reading_order(api_client, dataset_id, monkeypatch):
    body, calls = _build_ranked(api_client, dataset_id, monkeypatch)
    did = body["dashboard"]["id"]
    r = api_client.patch(f"/dashboards/{did}", json={"priority_order": ["k2", "c", "t", "k1"]})
    assert r.status_code == 200, r.text
    w = _by_id(r.json()["data"]["spec"])
    assert [w[i]["priority"] for i in ("k2", "c", "t", "k1")] == [1, 2, 3, 4]
    assert (w["k2"]["layout"]["x"], w["k2"]["layout"]["y"]) == (0, 0)
    assert (w["k1"]["layout"]["x"], w["k1"]["layout"]["y"]) == (3, 0)
    assert w["c"]["layout"]["y"] < w["t"]["layout"]["y"]  # charts + tables follow priority
    assert len(calls) == 1
    data = api_client.get(f"/dashboards/{did}/data").json()["data"]
    assert [i["widget_id"] for i in data["insights"]] == ["k2", "k1"]


def test_patch_priority_without_rearrange_keeps_layout(api_client, dataset_id, monkeypatch):
    body, _ = _build_ranked(api_client, dataset_id, monkeypatch)
    did = body["dashboard"]["id"]
    before = {w["id"]: w["layout"] for w in body["dashboard"]["spec"]["widgets"]}
    r = api_client.patch(
        f"/dashboards/{did}", json={"priority_order": ["k2", "c", "t", "k1"], "rearrange": False}
    )
    assert r.status_code == 200, r.text
    w = _by_id(r.json()["data"]["spec"])
    assert {i: x["layout"] for i, x in w.items()} == before
    assert w["k2"]["priority"] == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"priority_order": ["k1", "k2", "t"]},  # incomplete
        {"priority_order": ["k1", "k1", "t", "c"]},  # duplicate
        {"priority_order": ["k1", "k2", "t", "nope"]},  # unknown id
        {"priority_order": "k1"},  # not a list
        {"priority_order": ["k1", "k2", "t", "c"], "rearrange": "yes"},
    ],
)
def test_patch_invalid_priority_leaves_spec_unchanged(api_client, dataset_id, monkeypatch, patch):
    body, _ = _build_ranked(api_client, dataset_id, monkeypatch)
    did = body["dashboard"]["id"]
    r = api_client.patch(f"/dashboards/{did}", json=patch)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_priority"
    assert api_client.get(f"/dashboards/{did}").json()["data"]["spec"] == body["dashboard"]["spec"]


def test_stored_v1_dashboard_opens_as_v2_and_is_rewritten_on_write(api_client, dataset_id):
    from db.models import DashboardRow
    from db.session import create_db_session

    v1 = {
        "version": 1,
        "title": "Old",
        "description": None,
        "widgets": [
            {"id": "c", "kind": "chart", "title": "Chart", "filters": [],
             "layout": {"x": 0, "y": 2, "w": 6, "h": 5},
             "chart": {"type": "bar", "x": "region", "y": {"field": "revenue", "agg": "sum"}}},
            {"id": "k", "kind": "kpi", "title": "Revenue", "filters": [],
             "layout": {"x": 0, "y": 0, "w": 3, "h": 2},
             "kpi": {"field": "revenue", "agg": "sum", "format": "number"}},
        ],
    }
    with create_db_session() as s:
        row = DashboardRow(dataset_id=dataset_id, title="Old", command="c", spec_json=v1, generation_json={})
        s.add(row)
        s.flush()
        did = row.id

    spec = api_client.get(f"/dashboards/{did}").json()["data"]["spec"]
    assert spec["version"] == 2 and spec["summary"] is None
    w = _by_id(spec)
    assert (w["k"]["priority"], w["c"]["priority"]) == (1, 2)  # reading order of the stored layout
    assert w["k"]["description_source"] == "auto" and w["k"]["description"]
    data = api_client.get(f"/dashboards/{did}/data").json()["data"]
    assert [i["widget_id"] for i in data["insights"]] == ["k"]
    with create_db_session() as s:
        assert s.get(DashboardRow, did).spec_json["version"] == 1  # reading never writes

    r = api_client.patch(f"/dashboards/{did}", json={"priority_order": ["c", "k"], "rearrange": False})
    assert r.status_code == 200, r.text
    with create_db_session() as s:
        stored = s.get(DashboardRow, did).spec_json
    assert stored["version"] == 2
    assert {x["id"]: x["priority"] for x in stored["widgets"]} == {"c": 1, "k": 2}


# --- chat: edit an existing dashboard ----------------------------------------


def _chat(client, dash_id, message="remove the table"):
    return client.post(f"/dashboards/{dash_id}/chat", json={"message": message})


def test_chat_edits_dashboard_and_persists(api_client, dataset_id, monkeypatch):
    _fake_llm(monkeypatch, [json.dumps(GOOD)])
    dash_id = _create(api_client, dataset_id).json()["data"]["dashboard"]["id"]

    edited = {**GOOD, "title": "Sales (no table)", "reply": "Removed the table.",
              "widgets": [w for w in GOOD["widgets"] if w["kind"] != "table"]}
    calls = _fake_llm(monkeypatch, [json.dumps(edited)])
    r = _chat(api_client, dash_id)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert len(calls) == 1 and "Current dashboard" in calls[0]
    assert body["changed"] is True and body["reply"] == "Removed the table."
    assert _kinds(body["dashboard"]["spec"]) == ["kpi", "chart"]
    assert set(body["data"]["widgets"]) == {"w1", "w2"}
    got = api_client.get(f"/dashboards/{dash_id}").json()["data"]
    assert got["title"] == "Sales (no table)" and _kinds(got["spec"]) == ["kpi", "chart"]


def test_chat_unusable_reply_leaves_dashboard_unchanged(api_client, dataset_id, monkeypatch):
    _fake_llm(monkeypatch, [json.dumps(GOOD)])
    dash_id = _create(api_client, dataset_id).json()["data"]["dashboard"]["id"]
    _fake_llm(monkeypatch, ["not json at all"])
    r = _chat(api_client, dash_id)
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["changed"] is False and "unchanged" in body["reply"]
    assert _kinds(body["dashboard"]["spec"]) == ["kpi", "chart", "table"]


def test_chat_validation_errors(api_client, dataset_id, monkeypatch):
    _fake_llm(monkeypatch, [json.dumps(GOOD)])
    dash_id = _create(api_client, dataset_id).json()["data"]["dashboard"]["id"]
    assert _chat(api_client, dash_id, "   ").status_code == 400
    assert _chat(api_client, "nope").status_code == 404


# --- dataset type + AI insights ----------------------------------------------


def test_detect_domain_variants():
    from graph.dashboard_insights import detect_domain

    assert detect_domain(_sales_df())["key"] == "sales"
    hr = pd.DataFrame({"employee_id": [1], "Department": ["A"], "salary": [1.0], "hire_date": ["2020-01-01"]})
    assert detect_domain(hr)["key"] == "hr"
    stock = pd.DataFrame({"Date": ["2024-01-01"], "Open": [1.0], "High": [2.0], "Low": [1.0], "Close": [2.0], "Volume": [10]})
    assert detect_domain(stock)["key"] == "stock_market"
    assert detect_domain(pd.DataFrame({"foo": [1], "bar": [2]}))["key"] == "general"


def test_data_payload_has_domain_overview_and_insights(api_client, dataset_id, monkeypatch):
    _fake_llm(monkeypatch, [json.dumps(GOOD)])
    data = _create(api_client, dataset_id).json()["data"]["data"]
    assert data["domain"]["key"] == "sales" and data["domain"]["label"] == "Sales"
    assert data["overview"]["rows"] == 300 and data["overview"]["completeness"] == 100.0
    texts = [i["text"] for i in data["ai_insights"]]
    assert any("Revenue by region" in t and "%" in t for t in texts), texts


# --- domain hint reaches the prompt ------------------------------------------


def _hint_sales_df():
    return pd.DataFrame({
        "order_id": [1, 2, 3, 4],
        "product": ["a", "b", "a", "c"],
        "region": ["N", "S", "N", "E"],
        "revenue": [10.0, 20.0, 30.0, 40.0],
        "quantity": [1, 2, 3, 4],
    })


def test_domain_hint_in_build_and_refine_prompts(monkeypatch):
    import graph.dashboard as dash
    from graph.dashboard_insights import detect_domain, domain_hint

    df = _hint_sales_df()
    hint = domain_hint(detect_domain(df))
    assert hint and "Sales" in hint

    calls = _fake_llm(monkeypatch, [json.dumps(GOOD)])
    dash.build_dashboard("ds", "show revenue by region", df=df)
    assert "## Dataset type" in calls[0] and hint in calls[0]

    calls = _fake_llm(monkeypatch, [json.dumps(GOOD)])
    dash.refine_dashboard("remove the table", GOOD, df=df)
    assert "## Dataset type" in calls[0] and hint in calls[0]


def test_no_dataset_type_section_for_general_data():
    import graph.dashboard as dash

    assert "## Dataset type" not in dash._build_prompt("x", "{}", "")
    assert "## Dataset type" not in dash._refine_prompt("x", GOOD, "{}", "")
