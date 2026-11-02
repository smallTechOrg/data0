"""`/dashboards` routes (Phase 15 C40, Phase 16 C41) — agent-built dashboards.

Contract: `spec/api.md` -> "Agent-built Dashboards (C40, Phase 15)". Stored v1
specs are read as v2 (`upgrade_v1`) and rewritten as v2 on their next write. A dashboard
belongs to ONE dataset; the row stores the validated spec (incl. layout) and the
widget data is recomputed from the dataset's CURRENT file on every data fetch by
the safe aggregation engine (`graph.dashboard_data`). The build runs the
pipeline in `graph.dashboard` synchronously (the route is a sync `def`, so it
runs in the FastAPI threadpool like `/ask`).
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import api_error, ok
from db.models import DashboardRow, DatasetRow
from db.session import get_session
from graph import nodes as graph_nodes
from domain.dashboard import upgrade_v1
from graph.dashboard import assign_layout, build_dashboard, normalize_priorities, validate_layout
from graph.dashboard_data import build_insights, compute_widget_data
from observability.events import get_logger

router = APIRouter()
logger = get_logger("api.dashboards")

_MAX_COMMAND = 1000
_MAX_TITLE = 80


class DashboardCreate(BaseModel):
    command: str = ""
    title: str | None = None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _filename(session: Session, dataset_id: str) -> str | None:
    ds = session.get(DatasetRow, dataset_id)
    return ds.filename if ds is not None else None


def _record(row: DashboardRow, filename: str | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "dataset_id": row.dataset_id,
        "dataset_filename": filename,
        "title": row.title,
        "command": row.command,
        "spec": upgrade_v1(row.spec_json),
        "generation": row.generation_json or {},
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _get_row(session: Session, dashboard_id: str) -> DashboardRow:
    row = session.get(DashboardRow, dashboard_id)
    if row is None:
        raise api_error("dashboard_not_found", f"Dashboard {dashboard_id} not found", 404)
    return row


def _data_payload(row: DashboardRow, df) -> dict[str, Any]:
    spec = upgrade_v1(row.spec_json)
    widgets = compute_widget_data(df, spec)
    return {
        "dashboard_id": row.id,
        "dataset_id": row.dataset_id,
        "row_count": int(len(df)),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "insights": build_insights(spec, widgets),
        "widgets": widgets,
    }


def _check_priority_order(order: Any, widget_ids: list[str]) -> list[str]:
    """Every widget id exactly once, or 400 `invalid_priority`."""
    if (
        not isinstance(order, list)
        or not all(isinstance(i, str) for i in order)
        or len(order) != len(widget_ids)
        or set(order) != set(widget_ids)
    ):
        raise api_error("invalid_priority", "priority_order must list every widget id exactly once.", 400)
    return order


def _commit(session: Session, what: str) -> None:
    """Commit or surface an honest 500 `write_failed` (rolled back)."""
    try:
        session.commit()
    except Exception as exc:  # noqa: BLE001 — an unpersisted write must not report ok
        session.rollback()
        logger.error("dashboard_commit_failed", what=what, error=str(exc)[:200])
        raise api_error("write_failed", f"Failed to persist dashboard: {exc}", 500)


@router.post("/datasets/{dataset_id}/dashboards")
def create_dashboard(
    dataset_id: str,
    body: DashboardCreate,
    session: Session = Depends(get_session),
) -> dict:
    ds = session.get(DatasetRow, dataset_id)
    if ds is None:
        raise api_error("dataset_not_found", f"Dataset {dataset_id} not found", 404)
    command = (body.command or "").strip()
    if not command:
        raise api_error("empty_command", "Describe the dashboard you want.", 400)
    if len(command) > _MAX_COMMAND:
        raise api_error(
            "command_too_long", f"Command must be at most {_MAX_COMMAND} characters.", 400
        )
    try:
        df = graph_nodes._load_dataframe(dataset_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("dashboard_load_failed", dataset_id=dataset_id, error=str(exc)[:200])
        raise api_error("dashboard_failed", f"Could not read the dataset file: {exc}", 500)
    if len(df) == 0 or len(df.columns) == 0:
        raise api_error("empty_dataset", "The dataset has no rows or no columns.", 400)

    notes = graph_nodes._facts_as_notes(ds.context_facts or [])
    filename = ds.filename
    try:
        build = build_dashboard(
            dataset_id, command, (body.title or "").strip() or None, df=df, notes=notes
        )
    except Exception as exc:  # noqa: BLE001 — a profile/compute crash is not a 5xx-less state
        logger.error("dashboard_build_failed", dataset_id=dataset_id, error=str(exc)[:200])
        raise api_error("dashboard_failed", f"Could not build the dashboard: {exc}", 500)

    row = DashboardRow(
        dataset_id=dataset_id,
        title=build.title[:_MAX_TITLE],
        command=command,
        spec_json=build.spec,
        generation_json=build.generation,
        tokens_input=build.tokens_input,
        tokens_output=build.tokens_output,
    )
    session.add(row)
    session.flush()
    _commit(session, "create")

    data = _data_payload(row, df)
    return ok({"dashboard": _record(row, filename), "data": data})


@router.get("/dashboards")
def list_dashboards(
    dataset_id: str | None = None, session: Session = Depends(get_session)
) -> dict:
    stmt = select(DashboardRow).order_by(DashboardRow.updated_at.desc())
    if dataset_id:
        stmt = stmt.where(DashboardRow.dataset_id == dataset_id)
    rows = session.execute(stmt).scalars().all()
    names = {d.id: d.filename for d in session.execute(select(DatasetRow)).scalars().all()}
    items = []
    for r in rows:
        widgets = (r.spec_json or {}).get("widgets") or []
        items.append(
            {
                "id": r.id,
                "dataset_id": r.dataset_id,
                "dataset_filename": names.get(r.dataset_id),
                "title": r.title,
                "command": r.command,
                "widget_count": len(widgets),
                "used_fallback": bool((r.generation_json or {}).get("used_fallback")),
                "created_at": _iso(r.created_at),
                "updated_at": _iso(r.updated_at),
            }
        )
    return ok(items)


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: str, session: Session = Depends(get_session)) -> dict:
    row = _get_row(session, dashboard_id)
    return ok(_record(row, _filename(session, row.dataset_id)))


@router.get("/dashboards/{dashboard_id}/data")
def get_dashboard_data(dashboard_id: str, session: Session = Depends(get_session)) -> dict:
    row = _get_row(session, dashboard_id)
    if session.get(DatasetRow, row.dataset_id) is None:
        raise api_error("dataset_not_found", f"Dataset {row.dataset_id} not found", 404)
    try:
        df = graph_nodes._load_dataframe(row.dataset_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("dashboard_data_load_failed", dashboard_id=dashboard_id, error=str(exc)[:200])
        raise api_error("dashboard_failed", f"Could not read the dataset file: {exc}", 500)
    return ok(_data_payload(row, df))


@router.patch("/dashboards/{dashboard_id}")
def patch_dashboard(
    dashboard_id: str,
    body: Any = Body(default=None),
    session: Session = Depends(get_session),
) -> dict:
    row = _get_row(session, dashboard_id)
    if not isinstance(body, dict) or not any(k in body for k in ("title", "layout", "priority_order")):
        raise api_error("empty_patch", "Provide a title, a layout and/or a priority_order to update.", 400)

    new_title: str | None = None
    if "title" in body:
        t = body["title"]
        if not isinstance(t, str) or not t.strip() or len(t.strip()) > _MAX_TITLE:
            raise api_error("invalid_title", f"Title must be 1-{_MAX_TITLE} characters.", 400)
        new_title = " ".join(t.split())

    spec = copy.deepcopy(upgrade_v1(row.spec_json))
    if "priority_order" in body:
        order = _check_priority_order(body["priority_order"], [w["id"] for w in spec.get("widgets", [])])
        rearrange = body.get("rearrange", True)
        if not isinstance(rearrange, bool):
            raise api_error("invalid_priority", "rearrange must be true or false.", 400)
        ranks = {wid: rank for rank, wid in enumerate(order, start=1)}
        widgets = normalize_priorities([{**w, "priority": ranks[w["id"]]} for w in spec["widgets"]])
        # An explicit layout in the same request wins over the automatic re-pack.
        spec["widgets"] = assign_layout(widgets) if rearrange and "layout" not in body else widgets
    if "layout" in body:
        ids = [w["id"] for w in spec.get("widgets", [])]
        clean, err = validate_layout(body["layout"], ids)
        if err is not None:
            raise api_error("invalid_layout", err, 400)
        rects = {e["id"]: e for e in clean or []}
        for w in spec["widgets"]:
            r = rects[w["id"]]
            w["layout"] = {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}
    if new_title is not None:
        spec["title"] = new_title
        row.title = new_title

    row.spec_json = spec  # new object so the JSON column change is detected
    row.updated_at = datetime.now(timezone.utc)
    _commit(session, "patch")
    return ok(_record(row, _filename(session, row.dataset_id)))


@router.delete("/dashboards/{dashboard_id}")
def delete_dashboard(dashboard_id: str, session: Session = Depends(get_session)) -> dict:
    row = _get_row(session, dashboard_id)
    session.delete(row)
    return ok({"deleted": True})
