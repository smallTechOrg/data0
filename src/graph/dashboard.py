"""Dashboard builder pipeline (C40 Phase 15, C41 Phase 16) — graph-adjacent, NOT a ReAct graph.

`build_dashboard(dataset_id, command, title=None)` is a fixed linear pipeline:
profile -> ONE structured LLM call (<= 1 repair) -> strict `validate_spec` against
the real columns -> deterministic `fallback_spec` when the LLM output is unusable
-> server-assigned layout. The LLM emits JSON only; it never writes code and
never emits coordinates. See `spec/agent.md` -> "Dashboard builder pipeline (C40)".

Pure functions here (`validate_spec`, `assign_layout`, `validate_layout`,
`fallback_spec`) are unit-tested without any LLM.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from domain.dashboard import (
    DESCRIPTION_MAX,
    GRID_COLUMNS,
    MAX_WIDGETS,
    RATIONALE_MAX,
    SUMMARY_MAX,
    DashboardSpec,
    Widget,
)
from graph.dashboard_charts import clamp_chart_type, find_column, is_ordered, rationale_for
from graph.dashboard_insights import detect_domain, domain_hint
from graph.dashboard_profile import columns_schema_for, profile_dataframe
from llm.client import LLMClient
from observability.events import get_logger

logger = get_logger("graph.dashboard")

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "dashboard.md"
DASHBOARD_TAG = "<node:dashboard>"
_NOTES_MAX_CHARS = 1500

_NUMERIC = {"integer", "float"}
_AGG_OPS = ("sum", "mean", "median", "min", "max", "count", "nunique")
_FILTER_OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "in", "not_null")
_CHART_TYPES = ("bar", "line", "area", "pie", "scatter", "histogram")
_GRAINS = ("day", "week", "month", "quarter", "year")
_SORTS = ("x_asc", "x_desc", "y_asc", "y_desc")
_FORMATS = ("number", "integer", "currency", "percent")
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_DEFAULT_SIZE = {"kpi": (3, 2), "chart": (6, 5), "table": (12, 6)}
_KIND_ORDER = {"kpi": 0, "chart": 1, "table": 2}
_DESCRIPTION_SOURCES = ("agent", "auto", "user")
_AGG_WORDS = {
    "sum": "Total",
    "mean": "Average",
    "median": "Median",
    "min": "Minimum",
    "max": "Maximum",
    "count": "Count",
    "nunique": "Distinct count",
}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _norm(name: str) -> str:
    return " ".join(str(name).split()).lower()


class _Err(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _snap(name: Any, schema: dict[str, str]) -> str:
    """Exact column name, else a UNIQUE case/whitespace-insensitive match."""
    if not isinstance(name, str) or not name.strip():
        raise _Err("unknown_field", f"field {name!r} is not a column name")
    if name in schema:
        return name
    matches = [c for c in schema if _norm(c) == _norm(name)]
    if len(matches) == 1:
        return matches[0]
    raise _Err("unknown_field", f"{name}")


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _check_agg(agg: Any, alias: str | None, field_name: str | None) -> str:
    """Return the agg; enforce closed set + dtype compatibility."""
    if agg not in _AGG_OPS:
        raise _Err("bad_agg", f"unsupported aggregation {agg!r}")
    if field_name is None:
        if agg != "count":
            raise _Err("bad_agg", f"'{agg}' needs a field (only count may omit it)")
        return agg
    assert alias is not None
    if agg in ("sum", "mean", "median") and alias not in _NUMERIC:
        raise _Err("agg_dtype_mismatch", f"{agg} needs a numeric field; '{field_name}' is {alias}")
    if agg in ("min", "max") and alias not in _NUMERIC | {"datetime"}:
        raise _Err("agg_dtype_mismatch", f"{agg} needs a numeric or datetime field; '{field_name}' is {alias}")
    return agg


def _opt_field(value: Any, schema: dict[str, str]) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _snap(value, schema)


def _validate_filter(raw: Any, schema: dict[str, str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _Err("bad_filter", "filter must be an object {field, op, value}")
    fname = _snap(raw.get("field"), schema)
    op = raw.get("op")
    if op not in _FILTER_OPS:
        raise _Err("bad_filter", f"unsupported filter op {op!r}")
    alias = schema[fname]
    value = raw.get("value")
    if op == "not_null":
        return {"field": fname, "op": op, "value": None}
    if op == "in":
        if not isinstance(value, list) or not value:
            raise _Err("bad_filter", "'in' needs a non-empty list value")
        value = value[:50]
        items = value
    else:
        if value is None or isinstance(value, (list, dict)):
            raise _Err("bad_filter", f"'{op}' needs a scalar value")
        items = [value]
    if op in ("gt", "gte", "lt", "lte") and alias not in _NUMERIC | {"datetime"}:
        raise _Err("bad_filter", f"'{op}' is only valid on numeric/datetime fields; '{fname}' is {alias}")
    for item in items:
        if alias in _NUMERIC:
            try:
                float(item)
            except (TypeError, ValueError):
                raise _Err("bad_filter", f"value {item!r} is not numeric for '{fname}'") from None
        elif alias == "datetime":
            try:
                pd.Timestamp(item)
            except (TypeError, ValueError):
                raise _Err("bad_filter", f"value {item!r} is not a date for '{fname}'") from None
    return {"field": fname, "op": op, "value": value}


def _validate_kpi(cfg: Any, schema: dict[str, str]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise _Err("bad_shape", "kpi config must be an object")
    fname = _opt_field(cfg.get("field"), schema)
    agg = _check_agg(cfg.get("agg"), schema.get(fname) if fname else None, fname)
    fmt = cfg.get("format") if cfg.get("format") in _FORMATS else "number"
    out = {"field": fname, "agg": agg, "format": fmt, "prefix": None, "suffix": None}
    for k in ("prefix", "suffix"):
        v = cfg.get(k)
        if isinstance(v, str) and v:
            out[k] = v[:8]
    return out


def _validate_chart(cfg: Any, schema: dict[str, str]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise _Err("bad_shape", "chart config must be an object")
    ctype = cfg.get("type")
    if ctype not in _CHART_TYPES:
        raise _Err("bad_chart_type", f"unsupported chart type {ctype!r}")
    x = _snap(cfg.get("x"), schema)
    xa = schema[x]
    y_out: dict[str, Any] | None = None
    if ctype != "histogram":
        y = cfg.get("y")
        if not isinstance(y, dict):
            raise _Err("bad_shape", f"{ctype} chart needs y: {{field, agg}}")
        yf = _opt_field(y.get("field"), schema)
        agg = y.get("agg")
        if ctype == "scatter":
            if yf is None:
                raise _Err("bad_shape", "scatter needs a numeric y field")
            agg = "none"
        elif agg == "none":
            raise _Err("bad_agg", "'none' is only valid for scatter charts")
        else:
            _check_agg(agg, schema.get(yf) if yf else None, yf)
        y_out = {"field": yf, "agg": agg}
    # axis dtype coherence
    if ctype == "histogram" and xa not in _NUMERIC:
        raise _Err("axis_dtype_mismatch", f"histogram x must be numeric; '{x}' is {xa}")
    if ctype == "scatter":
        if xa not in _NUMERIC or schema[y_out["field"]] not in _NUMERIC:  # type: ignore[index]
            raise _Err("axis_dtype_mismatch", "scatter x and y must both be numeric")
    if ctype in ("line", "area") and xa not in _NUMERIC | {"datetime"}:
        raise _Err("axis_dtype_mismatch", f"{ctype} x must be datetime or numeric; '{x}' is {xa}")
    if ctype == "pie" and xa in _NUMERIC | {"datetime"}:
        raise _Err("axis_dtype_mismatch", f"pie x must be categorical; '{x}' is {xa}")
    series_by = None
    if ctype in ("bar", "line", "area"):
        series_by = _opt_field(cfg.get("series_by"), schema)
        if series_by is not None and schema[series_by] in _NUMERIC | {"datetime"}:
            raise _Err("axis_dtype_mismatch", f"series_by must be categorical; '{series_by}' is {schema[series_by]}")
    grain = cfg.get("time_grain") if (cfg.get("time_grain") in _GRAINS and xa == "datetime") else None
    sort = cfg.get("sort") if cfg.get("sort") in _SORTS else None
    return {
        "type": ctype,
        "x": x,
        "y": y_out,
        "series_by": series_by,
        "time_grain": grain,
        "sort": sort,
        "limit": _clamp(cfg.get("limit"), 1, 50, 20),
        "bins": _clamp(cfg.get("bins"), 5, 50, 20),
    }


def _validate_table(cfg: Any, schema: dict[str, str]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise _Err("bad_shape", "table config must be an object")
    columns, group_by = cfg.get("columns"), cfg.get("group_by")
    raw_mode = isinstance(columns, list) and len(columns) > 0
    grouped_mode = isinstance(group_by, list) and len(group_by) > 0
    if raw_mode == grouped_mode:
        raise _Err("bad_table_mode", "table needs EITHER columns (raw) OR group_by+aggs (grouped), not both/neither")
    limit = _clamp(cfg.get("limit"), 1, 50, 10)
    sort_by = cfg.get("sort_by") if isinstance(cfg.get("sort_by"), str) else None
    sort_dir = cfg.get("sort_dir") if cfg.get("sort_dir") in ("asc", "desc") else None
    if raw_mode:
        cols = [_snap(c, schema) for c in columns[:12]]
        names = cols
        out: dict[str, Any] = {"columns": cols, "group_by": None, "aggs": None}
    else:
        gb = [_snap(c, schema) for c in group_by[:3]]
        raw_aggs = cfg.get("aggs")
        if not isinstance(raw_aggs, list) or not raw_aggs:
            raise _Err("bad_table_mode", "grouped table needs at least one agg")
        aggs: list[dict[str, Any]] = []
        names = list(gb)
        for a in raw_aggs[:6]:
            if not isinstance(a, dict):
                raise _Err("bad_shape", "agg must be an object {field, agg, alias}")
            f = _opt_field(a.get("field"), schema)
            op = _check_agg(a.get("agg"), schema.get(f) if f else None, f)
            alias = a.get("alias") if isinstance(a.get("alias"), str) and a.get("alias").strip() else None
            alias = alias.strip()[:40] if alias else None
            aggs.append({"field": f, "agg": op, "alias": alias})
            names.append(alias or ("count" if f is None else f"{op}_{f}"))
        out = {"columns": None, "group_by": gb, "aggs": aggs}
    if sort_by is not None and sort_by not in names:
        snapped = [n for n in names if _norm(n) == _norm(sort_by)]
        sort_by = snapped[0] if len(snapped) == 1 else None
    out.update({"sort_by": sort_by, "sort_dir": sort_dir, "limit": limit})
    return out


def _clean_layout(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    try:
        vals = {k: raw[k] for k in ("x", "y", "w", "h")}
    except KeyError:
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in vals.values()):
        return None
    if vals["x"] < 0 or vals["y"] < 0 or not (1 <= vals["w"] <= GRID_COLUMNS):
        return None
    if vals["x"] + vals["w"] > GRID_COLUMNS or not (1 <= vals["h"] <= 12):
        return None
    return vals


def _clean_text(value: Any, limit: int) -> str | None:
    """Plain one-line text, truncated (never rejected); None when empty/non-string."""
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


def _measure_text(field_name: Any, agg: Any) -> str:
    if field_name is None:
        return "Row count"
    return f"{_AGG_WORDS.get(agg, agg)} of {field_name}"


def auto_caption(widget: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    """Deterministic description for a widget the agent left undescribed (C41)."""
    kind = widget.get("kind")
    if kind == "kpi":
        cfg = widget["kpi"]
        rows = (profile or {}).get("row_count")
        scope = "the filtered rows" if widget.get("filters") else (f"all {rows:,} rows" if rows else "all rows")
        text = f"{_measure_text(cfg.get('field'), cfg.get('agg'))} across {scope}."
    elif kind == "chart":
        cfg = widget["chart"]
        y = cfg.get("y") or {}
        if cfg.get("type") == "histogram":
            text = f"Distribution of {cfg.get('x')}."
        elif cfg.get("type") == "scatter":
            text = f"{y.get('field')} plotted against {cfg.get('x')}."
        else:
            text = f"{_measure_text(y.get('field'), y.get('agg'))} by {cfg.get('x')}"
            if cfg.get("series_by"):
                text += f", split by {cfg['series_by']}"
            col = find_column(profile, cfg.get("x"))
            limit = cfg.get("limit")
            if col and limit and int(col.get("nunique") or 0) > limit and not is_ordered(col):
                text += f", top {limit}"
            text += "."
    else:
        cfg = widget["table"]
        if cfg.get("group_by"):
            first = (cfg.get("aggs") or [{}])[0]
            text = (
                f"{_measure_text(first.get('field'), first.get('agg'))} by "
                f"{', '.join(cfg['group_by'])}, up to {cfg.get('limit')} rows."
            )
        else:
            text = f"Rows of {', '.join((cfg.get('columns') or [])[:4])}, up to {cfg.get('limit')} rows."
    return text[:DESCRIPTION_MAX]


def _auto_summary(profile: dict[str, Any]) -> str:
    return f"Overview of {profile['row_count']:,} rows across {profile['col_count']:,} columns."[:SUMMARY_MAX]


def _clamp_chart(
    cfg: dict[str, Any], profile: dict[str, Any], notes: list[str] | None
) -> tuple[dict[str, Any], bool]:
    """Hard chart clamps (pie > 8 categories, line/area on unordered x -> bar)."""
    ctype = cfg.get("type")
    new_type, note = clamp_chart_type(
        ctype, find_column(profile, cfg.get("x")), limit=_clamp(cfg.get("limit"), 1, 50, 20)
    )
    if new_type == ctype:
        return cfg, False
    if notes is not None and note:
        notes.append(note)
    out = {**cfg, "type": new_type}
    if ctype == "pie" and not out.get("sort"):
        out["sort"] = "y_desc"
    return out, True


def normalize_priorities(widgets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dense unique ranks 1..N. Widgets keep their list position; only `priority` changes.

    Sorted by the given priority; missing/non-int/out-of-range values rank after
    valid ones, and reply order breaks every tie (so duplicates stay deterministic).
    """

    def given(w: dict[str, Any]) -> int | None:
        p = w.get("priority")
        return p if isinstance(p, int) and not isinstance(p, bool) and p >= 1 else None

    order = sorted(
        range(len(widgets)),
        key=lambda i: (given(widgets[i]) is None, given(widgets[i]) or 0, i),
    )
    ranks = {i: rank for rank, i in enumerate(order, start=1)}
    return [{**w, "priority": ranks[i]} for i, w in enumerate(widgets)]


def _validate_widget(
    raw: Any,
    schema: dict[str, str],
    profile: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _Err("bad_shape", "widget must be an object")
    kind = raw.get("kind")
    if kind not in _KIND_ORDER:
        raise _Err("unknown_kind", f"unknown widget kind {kind!r}")
    if not isinstance(raw.get(kind), dict):
        raise _Err("bad_shape", f"widget kind '{kind}' needs a '{kind}' config block")
    filters_raw = raw.get("filters") or []
    if not isinstance(filters_raw, list):
        raise _Err("bad_filter", "filters must be a list")
    filters = [_validate_filter(f, schema) for f in filters_raw[:5]]
    raw_cfg, clamped = raw[kind], False
    if kind == "chart" and profile is not None:
        raw_cfg, clamped = _clamp_chart(raw_cfg, profile, notes)
    cfg = {
        "kpi": _validate_kpi,
        "chart": _validate_chart,
        "table": _validate_table,
    }[kind](raw_cfg, schema)
    title = raw.get("title")
    title = " ".join(title.split())[:80] if isinstance(title, str) and title.strip() else ""
    if not title:
        title = {"kpi": "Metric", "chart": "Chart", "table": "Table"}[kind]
    widget = {
        "id": raw.get("id"),
        "kind": kind,
        "title": title,
        "layout": _clean_layout(raw.get("layout")),
        "filters": filters,
        "kpi": None,
        "chart": None,
        "table": None,
    }
    widget[kind] = cfg
    description = _clean_text(raw.get("description"), DESCRIPTION_MAX)
    source = raw.get("description_source")
    widget.update(
        priority=raw.get("priority"),  # made dense by normalize_priorities
        description=description or auto_caption(widget, profile),
        description_source=(
            "auto" if description is None else source if source in _DESCRIPTION_SOURCES else "agent"
        ),
        ignore_dashboard_filters=raw.get("ignore_dashboard_filters") is True,
    )
    if kind == "chart":
        # A clamped type invalidates the agent's justification, so it is re-derived.
        rationale = None if clamped else _clean_text(raw.get("chart_rationale"), RATIONALE_MAX)
        widget["chart_rationale"] = rationale or rationale_for(cfg, profile)
    return widget


def validate_spec(
    spec: Any,
    columns_schema: dict[str, str],
    *,
    profile: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate a (possibly LLM-written) spec against the dataset's real columns.

    Returns `(clean_widgets, errors)`; errors are `{widget_index, code, detail}`
    (`widget_index` is None for whole-reply errors). Widget-by-widget: an invalid
    widget is an error entry and is NOT in `clean_widgets`. Field names are snapped
    (unique case/whitespace-insensitive), ranges clamped, ids made unique,
    priorities made dense, missing text filled deterministically. With `profile`,
    the chart-type clamps also run (they need cardinalities) and record `notes`.
    """
    if not isinstance(spec, dict):
        return [], [{"widget_index": None, "code": "bad_shape", "detail": "reply must be a JSON object"}]
    widgets = spec.get("widgets")
    if not isinstance(widgets, list):
        return [], [{"widget_index": None, "code": "bad_shape", "detail": "reply needs a 'widgets' list"}]

    clean: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for i, raw in enumerate(widgets):
        if i >= MAX_WIDGETS:
            errors.append(
                {"widget_index": i, "code": "too_many_widgets", "detail": f"at most {MAX_WIDGETS} widgets allowed"}
            )
            continue
        try:
            clean.append(_validate_widget(raw, columns_schema, profile, notes))
        except _Err as exc:
            errors.append({"widget_index": i, "code": exc.code, "detail": exc.detail})
        except (TypeError, ValueError, AttributeError) as exc:  # defensive: odd shapes
            errors.append({"widget_index": i, "code": "bad_shape", "detail": str(exc)[:200]})

    # ids: unique + well-formed; the server assigns w1..wN when missing/duplicate.
    seen: set[str] = set()
    pending = []
    for w in clean:
        wid = w["id"]
        if isinstance(wid, str) and _ID_RE.match(wid) and wid not in seen:
            seen.add(wid)
        else:
            pending.append(w)
    n = 1
    for w in pending:
        while f"w{n}" in seen:
            n += 1
        w["id"] = f"w{n}"
        seen.add(w["id"])

    # Final shape gate through the Pydantic models (belt and braces).
    final: list[dict[str, Any]] = []
    for i, w in enumerate(normalize_priorities(clean)):
        try:
            final.append(Widget.model_validate(w).model_dump(mode="json"))
        except ValidationError as exc:
            errors.append({"widget_index": i, "code": "bad_shape", "detail": str(exc)[:200]})
    return normalize_priorities(final), errors


def validate_layout(
    layout: Any, widget_ids: list[str]
) -> tuple[list[dict[str, int]] | None, str | None]:
    """Check a layout list against the widget ids. Returns `(clean, error_message)`."""
    if not isinstance(layout, list) or not layout:
        return None, "layout must be a non-empty list"
    by_id: dict[str, dict[str, int]] = {}
    for entry in layout:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            return None, "each layout entry needs an id"
        wid = entry["id"]
        if wid in by_id:
            return None, f"duplicate widget id '{wid}'"
        rect = _clean_layout(entry)
        if rect is None:
            return None, f"widget '{wid}' has an invalid or out-of-bounds rectangle"
        by_id[wid] = rect
    unknown = [i for i in by_id if i not in widget_ids]
    if unknown:
        return None, f"unknown widget id '{unknown[0]}'"
    missing = [i for i in widget_ids if i not in by_id]
    if missing:
        return None, f"layout is missing widget id '{missing[0]}'"
    items = list(by_id.items())
    for a in range(len(items)):
        ia, ra = items[a]
        for b in range(a + 1, len(items)):
            ib, rb = items[b]
            if (
                ra["x"] < rb["x"] + rb["w"]
                and rb["x"] < ra["x"] + ra["w"]
                and ra["y"] < rb["y"] + rb["h"]
                and rb["y"] < ra["y"] + ra["h"]
            ):
                return None, f"widgets '{ia}' and '{ib}' overlap"
    return [{"id": i, **r} for i, r in by_id.items()], None


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def assign_layout(widgets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order KPIs by priority, then charts + tables merged by priority, and
    first-fit pack on the 12-col grid (equal/absent priorities: chart before table).

    A widget keeps its `w`/`h` if it already has a valid layout; otherwise the
    default size for its kind. Contract vectors in `spec/api.md`.
    """

    def rank(w: dict[str, Any]) -> float:
        p = w.get("priority")
        return p if isinstance(p, int) and not isinstance(p, bool) else float("inf")

    ordered = sorted(
        widgets,
        key=lambda w: (w.get("kind") != "kpi", rank(w), _KIND_ORDER.get(w.get("kind"), 9)),
    )
    occupied: set[tuple[int, int]] = set()
    placed: list[dict[str, Any]] = []
    for w in ordered:
        dw, dh = _DEFAULT_SIZE.get(w.get("kind"), (6, 5))
        cur = _clean_layout(w.get("layout"))
        ww, hh = (cur["w"], cur["h"]) if cur else (dw, dh)
        y = 0
        while True:
            hit = None
            for x in range(0, GRID_COLUMNS - ww + 1):
                if all(
                    (cx, cy) not in occupied
                    for cx in range(x, x + ww)
                    for cy in range(y, y + hh)
                ):
                    hit = x
                    break
            if hit is not None:
                break
            y += 1
        for cx in range(hit, hit + ww):
            for cy in range(y, y + hh):
                occupied.add((cx, cy))
        placed.append({**w, "layout": {"x": hit, "y": y, "w": ww, "h": hh}})
    return placed


# --------------------------------------------------------------------------- #
# Deterministic fallback
# --------------------------------------------------------------------------- #


def _drop_unrequested_row_count(widgets: list[dict[str, Any]], command: str) -> list[dict[str, Any]]:
    """Drop plain row-count KPIs ("Total records") unless the user asked for a count."""
    if re.search(r"(count|rows?|records?|how many|number of)", command or "", re.I):
        return widgets
    kept = [
        w for w in widgets
        if not (w.get("kind") == "kpi" and w["kpi"].get("field") is None and w["kpi"].get("agg") == "count")
    ]
    return kept or widgets


def fallback_spec(profile: dict[str, Any], command: str = "") -> dict[str, Any]:
    """Deterministic dashboard from the profile alone (no LLM). Layout unassigned."""
    cols = profile["columns"]
    measures = [c["name"] for c in cols if c["role"] == "measure"]
    dims = [c["name"] for c in cols if c["role"] == "dimension"]
    times = [c["name"] for c in cols if c["role"] == "time"]
    widgets: list[dict[str, Any]] = []
    for i, m in enumerate(measures[:3]):
        widgets.append(
            {
                "id": f"k{i + 2}", "kind": "kpi", "title": f"Total {m}",
                "kpi": {"field": m, "agg": "sum", "format": "number"},
            }
        )
    if dims:
        y = {"field": measures[0], "agg": "sum"} if measures else {"field": None, "agg": "count"}
        what = f"{measures[0]} by {dims[0]}" if measures else f"Rows by {dims[0]}"
        widgets.append(
            {
                "id": "c1", "kind": "chart", "title": what.capitalize(),
                "chart": {"type": "bar", "x": dims[0], "y": y, "sort": "y_desc", "limit": 10},
            }
        )
    if times:
        y = {"field": measures[0], "agg": "sum"} if measures else {"field": None, "agg": "count"}
        what = f"{measures[0]} over time" if measures else "Rows over time"
        widgets.append(
            {
                "id": "c2", "kind": "chart", "title": what.capitalize(),
                "chart": {"type": "line", "x": times[0], "y": y, "sort": "x_asc"},
            }
        )
    elif measures:
        widgets.append(
            {
                "id": "c2", "kind": "chart", "title": f"Distribution of {measures[0]}",
                "chart": {"type": "histogram", "x": measures[0]},
            }
        )
    names = [c["name"] for c in cols][:8]
    widgets.append(
        {
            "id": "t1", "kind": "table", "title": "Data preview",
            "table": {"columns": names, "limit": 10},
        }
    )
    # Ranking: measure KPIs -> charts -> table. No plain row-count KPI: it is noise.
    ranked = sorted(widgets, key=lambda w: _KIND_ORDER[w["kind"]])
    for rank, w in enumerate(ranked, start=1):
        w["priority"] = rank
    clean, _errors = validate_spec({"widgets": widgets}, profile["columns_schema"], profile=profile)
    return {
        "version": 2,
        "title": "Automatic dashboard",
        "summary": _auto_summary(profile),
        "description": None,
        "filters": [],
        "widgets": clean,
    }


# --------------------------------------------------------------------------- #
# LLM pipeline
# --------------------------------------------------------------------------- #

_NOPARSE = object()


def _extract_json(text: str) -> Any:
    """Bare JSON, fenced block, or `{...}` span in prose; `_NOPARSE` otherwise."""
    raw = (text or "").strip()
    if not raw:
        return _NOPARSE
    candidates = [raw]
    fence = re.search(r"```(?:json|JSON)?\s*\n?(.*?)```", raw, re.DOTALL)
    if fence:
        candidates.append(fence.group(1).strip())
    first, last = raw.find("{"), raw.rfind("}")
    if first != -1 and last > first:
        candidates.append(raw[first : last + 1])
    for cand in candidates:
        try:
            return json.loads(cand)
        except (ValueError, TypeError):
            continue
    return _NOPARSE


def _estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def _notes_text(notes: str) -> str:
    return (notes or "").strip()[:_NOTES_MAX_CHARS]


@dataclass
class DashboardBuild:
    spec: dict[str, Any]
    generation: dict[str, Any]
    tokens_input: int = 0
    tokens_output: int = 0
    title: str = ""
    df: pd.DataFrame | None = field(default=None, repr=False)


def _build_prompt(command: str, profile_text: str, notes: str, hint: str = "") -> str:
    parts = [
        f"{DASHBOARD_TAG}\n",
        f"## User command\n{command.strip()}\n",
        f"## Dataset profile (JSON; use ONLY these column names)\n{profile_text}\n",
    ]
    notes = _notes_text(notes)
    if notes:
        parts.append(f"## Dataset notes\n{notes}\n")
    if hint:
        parts.append(f"## Dataset type\n{hint}\n")
    parts.append(
        "Reply with ONLY a JSON object {\"title\": ...,\"summary\": ..., \"description\": ..., \"widgets\": [...]}. "
        "Every widget has a unique priority (1 = most important) and a description; charts also have chart_rationale. "
        "NO layout coordinates. 4-10 widgets; at least one kpi and one chart unless the data cannot support them."
    )
    return "\n".join(parts)


def _repair_prompt(prompt: str, previous: str, errors: list[dict[str, Any]]) -> str:
    lines = [
        f"- widget {e['widget_index'] if e['widget_index'] is not None else '(whole reply)'}: "
        f"{e['code']}: {e['detail']}"
        for e in errors[:20]
    ]
    return (
        prompt
        + "\n\n## Your previous reply\n"
        + (previous or "")[:4000]
        + "\n\n## Validation errors\n"
        + "\n".join(lines)
        + "\n\nReturn the corrected FULL JSON object only (fix or remove the invalid widgets)."
    )


def _agent_reply(reply: Any) -> Any:
    """Drop fields only the server may set from an LLM reply."""
    if not isinstance(reply, dict) or not isinstance(reply.get("widgets"), list):
        return reply
    widgets = [
        {k: v for k, v in w.items() if k != "description_source"} if isinstance(w, dict) else w
        for w in reply["widgets"]
    ]
    return {**reply, "widgets": widgets}


def _call_llm(client: Any, prompt: str, system: str) -> tuple[str, int, int]:
    resp = client.complete(prompt, system=system)
    text = getattr(resp, "text", None)
    if text is None:
        text = str(resp)
    tin = getattr(resp, "tokens_input", 0) or (_estimate_tokens(prompt) + _estimate_tokens(system))
    tout = getattr(resp, "tokens_output", 0) or _estimate_tokens(text)
    return text, int(tin), int(tout)


def build_dashboard(
    dataset_id: str,
    command: str,
    title: str | None = None,
    *,
    df: pd.DataFrame | None = None,
    notes: str = "",
) -> DashboardBuild:
    """Run the pipeline for a dataset. Never raises for LLM problems (-> fallback).

    A dataset that cannot be loaded raises (caller maps it to `dashboard_failed`).
    """
    started = time.monotonic()
    if df is None:
        from graph.nodes import _load_dataframe

        df = _load_dataframe(dataset_id)
    profile = profile_dataframe(df, notes)
    schema = profile["columns_schema"]
    logger.info("dashboard_profile", dataset_id=dataset_id, rows=profile["row_count"], cols=profile["col_count"])

    gen: dict[str, Any] = {
        "used_fallback": False,
        "repaired": False,
        "supplemented": [],
        "dropped_widgets": [],
        "notes": [],
        "model": "",
        "tokens_input": 0,
        "tokens_output": 0,
        "duration_ms": 0,
    }
    clean: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    agent_title: str | None = None
    agent_desc: str | None = None
    agent_summary: str | None = None
    clamp_notes: list[str] = []
    reply_used: Any = None

    system = _PROMPT_PATH.read_text(encoding="utf-8").strip()
    prompt = _build_prompt(command, profile["text"], notes, domain_hint(detect_domain(df)))
    try:
        client = LLMClient()
        gen["model"] = getattr(client, "model", "") or getattr(client, "provider", "") or ""
        text, tin, tout = _call_llm(client, prompt, system)
        gen["tokens_input"] += tin
        gen["tokens_output"] += tout
        logger.info("dashboard_llm", attempt=1, tokens_input=tin, tokens_output=tout)

        reply = _extract_json(text)
        if reply is _NOPARSE:
            clean, errors = [], [{"widget_index": None, "code": "bad_json", "detail": "reply was not valid JSON"}]
        else:
            clean, errors = validate_spec(_agent_reply(reply), schema, profile=profile, notes=clamp_notes)
            reply_used = reply
            if isinstance(reply, dict):
                agent_title, agent_desc = reply.get("title"), reply.get("description")
                agent_summary = reply.get("summary")
        logger.info("dashboard_validate", attempt=1, errors=[e["code"] for e in errors])

        if errors:  # ONE repair call
            gen["repaired"] = True
            text2, tin2, tout2 = _call_llm(client, _repair_prompt(prompt, text, errors), system)
            gen["tokens_input"] += tin2
            gen["tokens_output"] += tout2
            logger.info("dashboard_llm", attempt=2, tokens_input=tin2, tokens_output=tout2)
            reply2 = _extract_json(text2)
            if reply2 is _NOPARSE:
                if not clean:
                    errors = [{"widget_index": None, "code": "bad_json", "detail": "repair reply was not valid JSON"}]
                # else: keep the first attempt's valid widgets + its error list
            else:
                notes2: list[str] = []
                clean2, errors2 = validate_spec(_agent_reply(reply2), schema, profile=profile, notes=notes2)
                if clean2 or not clean:
                    clean, errors, clamp_notes = clean2, errors2, notes2
                    reply_used = reply2
                    if isinstance(reply2, dict):
                        agent_title = reply2.get("title") or agent_title
                        agent_desc = reply2.get("description") or agent_desc
                        agent_summary = reply2.get("summary") or agent_summary
            logger.info("dashboard_validate", attempt=2, errors=[e["code"] for e in errors])
    except Exception as exc:  # noqa: BLE001 — any LLM failure -> deterministic fallback
        gen["notes"].append(f"LLM unavailable: {type(exc).__name__}")
        logger.warning("dashboard_llm_failed", error=str(exc)[:200])
        clean, errors, reply_used = [], [], None

    # Dropped (still-invalid) widgets are recorded individually.
    for e in errors:
        if e["widget_index"] is not None:
            gen["dropped_widgets"].append(
                {"title": _raw_title(reply_used, e["widget_index"]), "reason": f"{e['code']}: {e['detail']}"[:200]}
            )

    fallback = fallback_spec(profile, command)
    if not clean:
        gen["used_fallback"] = True
        if not any(n.startswith("LLM unavailable") for n in gen["notes"]):
            gen["notes"].append("The AI reply could not be used; built an automatic dashboard.")
        logger.info("dashboard_fallback", reason=[e["code"] for e in errors])
        widgets = fallback["widgets"]
        agent_title = agent_desc = agent_summary = None
    else:
        gen["notes"].extend(clamp_notes)
        widgets = _drop_unrequested_row_count(list(clean), command)
        for kind in ("kpi", "chart"):
            if not any(w["kind"] == kind for w in widgets):
                extra = next((w for w in fallback["widgets"] if w["kind"] == kind), None)
                if extra is not None:
                    # Added on the agent's behalf, so it ranks after everything it chose.
                    widgets = widgets[: MAX_WIDGETS - 1] + [{**extra, "priority": MAX_WIDGETS + 1}]
                    gen["supplemented"].append(kind)
        widgets = normalize_priorities(_unique_ids(widgets))

    final_title = (title or "").strip() or (
        agent_title.strip() if isinstance(agent_title, str) and agent_title.strip() else ""
    ) or "Dashboard"
    final_title = " ".join(final_title.split())[:80]
    description = agent_desc.strip()[:300] if isinstance(agent_desc, str) and agent_desc.strip() else None

    spec = {
        "version": 2,
        "title": final_title,
        "summary": _clean_text(agent_summary, SUMMARY_MAX) or _auto_summary(profile),
        "description": description,
        "filters": [],
        "widgets": assign_layout(widgets),
    }
    # Safety net: re-validate the final spec; drop anything that no longer validates.
    safe, net_errors = validate_spec(spec, schema, profile=profile)
    if net_errors or not safe:
        logger.warning("dashboard_final_validation", errors=[e["code"] for e in net_errors])
        if not safe:
            safe = fallback["widgets"]
            gen["used_fallback"] = True
        spec["widgets"] = assign_layout(safe)
    else:
        spec["widgets"] = assign_layout(safe)
    DashboardSpec.model_validate(spec)

    gen["duration_ms"] = int((time.monotonic() - started) * 1000)
    logger.info(
        "dashboard_done",
        dataset_id=dataset_id,
        widgets=len(spec["widgets"]),
        used_fallback=gen["used_fallback"],
        duration_ms=gen["duration_ms"],
    )
    return DashboardBuild(
        spec=spec,
        generation=gen,
        tokens_input=gen["tokens_input"],
        tokens_output=gen["tokens_output"],
        title=final_title,
        df=df,
    )


def _unique_ids(widgets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    n = 1
    out = []
    for w in widgets:
        wid = w["id"]
        if wid in seen:
            while f"w{n}" in seen or f"w{n}" in {x["id"] for x in widgets}:
                n += 1
            wid = f"w{n}"
        seen.add(wid)
        out.append({**w, "id": wid})
    return out


def _raw_title(reply: Any, idx: int) -> str:
    """Title of the offending widget in the raw reply (for `dropped_widgets`)."""
    try:
        title = reply["widgets"][idx].get("title")
    except (TypeError, KeyError, IndexError, AttributeError):
        return ""
    return " ".join(title.split())[:80] if isinstance(title, str) else ""


_REFINE_SYSTEM_SUFFIX = (
    "\n\nYou are now EDITING an existing dashboard. Apply the user's request to the current "
    "dashboard: keep widgets the user did not mention, change/add/remove only what they asked for. "
    "Return the FULL updated JSON object (all widgets that should remain) and add a field "
    "\"reply\": ONE short plain-text sentence saying what you changed (no result values). "
    "If the request cannot be done with the available columns, return the dashboard unchanged "
    "and say why in \"reply\"."
)


def _refine_prompt(message: str, current: dict[str, Any], profile_text: str, notes: str, hint: str = "") -> str:
    keep = {
        "title": current.get("title"),
        "summary": current.get("summary"),
        "widgets": [
            {k: v for k, v in w.items() if k not in ("layout", "description_source")}
            for w in current.get("widgets", [])
        ],
    }
    parts = [
        f"{DASHBOARD_TAG}\n",
        f"## User request (edit the dashboard)\n{message.strip()}\n",
        f"## Current dashboard (JSON)\n{json.dumps(keep, default=str)[:12000]}\n",
        f"## Dataset profile (JSON; use ONLY these column names)\n{profile_text}\n",
    ]
    notes = _notes_text(notes)
    if notes:
        parts.append(f"## Dataset notes\n{notes}\n")
    if hint:
        parts.append(f"## Dataset type\n{hint}\n")
    parts.append(
        "Reply with ONLY a JSON object {\"title\",\"summary\", \"reply\", \"widgets\": [...]}. "
        "Every widget has a unique priority (1 = most important). NO layout coordinates."
    )
    return "\n".join(parts)


def refine_dashboard(
    message: str,
    current_spec: dict[str, Any],
    *,
    df: pd.DataFrame,
    notes: str = "",
) -> tuple[dict[str, Any] | None, str, int, int]:
    """Edit an existing dashboard from a chat message.

    Returns `(new_spec | None, assistant_reply, tokens_in, tokens_out)`. `None` means
    the spec is unchanged (LLM failure or an unusable reply) — never raises for LLM issues.
    """
    profile = profile_dataframe(df, notes)
    schema = profile["columns_schema"]
    system = _PROMPT_PATH.read_text(encoding="utf-8").strip() + _REFINE_SYSTEM_SUFFIX
    prompt = _refine_prompt(message, current_spec, profile["text"], notes, domain_hint(detect_domain(df)))
    try:
        client = LLMClient()
        text, tin, tout = _call_llm(client, prompt, system)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dashboard_refine_llm_failed", error=str(exc)[:200])
        return None, "I couldn't reach the AI just now, so the dashboard is unchanged.", 0, 0

    reply = _extract_json(text)
    if reply is _NOPARSE or not isinstance(reply, dict):
        return None, "I couldn't understand how to apply that, so the dashboard is unchanged.", tin, tout
    clean, errors = validate_spec(_agent_reply(reply), schema, profile=profile)
    if not clean:
        return None, "That change didn't fit the data's columns, so the dashboard is unchanged.", tin, tout

    said = _clean_text(reply.get("reply"), 300) or "Updated the dashboard."
    if errors:
        said += f" ({len(errors)} suggested widget{'s' if len(errors) != 1 else ''} couldn't be built and {'were' if len(errors) != 1 else 'was'} skipped.)"
    title = _clean_text(reply.get("title"), 80) or current_spec.get("title") or "Dashboard"
    spec = {
        **current_spec,
        "title": " ".join(str(title).split())[:80],
        "summary": _clean_text(reply.get("summary"), SUMMARY_MAX) or current_spec.get("summary"),
        "widgets": assign_layout(normalize_priorities(_unique_ids(clean))),
    }
    DashboardSpec.model_validate(spec)
    return spec, said, tin, tout
