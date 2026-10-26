"""Safe server-side aggregation engine for dashboard widgets (C40, Phase 15).

The safety boundary: the LLM only ever emits a declarative JSON spec; this module
computes every widget from that (already validated) spec with a CLOSED set of
pandas operations — filter -> group-by/resample -> one of 7 aggregations ->
sort/limit. No `eval`/`exec`, no string-built expressions: fields are used only
as column keys, ops are looked up in a fixed map.

`compute_widget_data(df, spec)` never raises for a single widget: a failing
widget becomes `{"kind", "status": "error", "message"}` and the rest still render.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as pdt

from graph.dashboard_profile import looks_like_dates
from graph.sandbox import _as_jsonable, _build_echart_option

_AGG_FUNCS = {
    "sum": "sum",
    "mean": "mean",
    "median": "median",
    "min": "min",
    "max": "max",
    "count": "count",
    "nunique": "nunique",
}
_PERIOD_FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
_MAX_SCATTER_POINTS = 2000
_MAX_SERIES = 8
_TABLE_MAX_ROWS = 50


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _to_datetime(series: pd.Series) -> pd.Series:
    if pdt.is_datetime64_any_dtype(series):
        return series
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(series, errors="coerce", format="mixed")


def _is_datetime_like(series: pd.Series) -> bool:
    return pdt.is_datetime64_any_dtype(series) or (
        not pdt.is_numeric_dtype(series) and looks_like_dates(series)
    )


def widget_fields(widget: dict[str, Any]) -> list[str]:
    """Every column a widget binds to (for the 'column no longer exists' check)."""
    fields: list[str] = []
    for f in widget.get("filters") or []:
        fields.append(f.get("field"))
    kind = widget.get("kind")
    if kind == "kpi":
        fields.append((widget.get("kpi") or {}).get("field"))
    elif kind == "chart":
        c = widget.get("chart") or {}
        fields += [c.get("x"), (c.get("y") or {}).get("field"), c.get("series_by")]
    elif kind == "table":
        t = widget.get("table") or {}
        fields += list(t.get("columns") or []) + list(t.get("group_by") or [])
        fields += [a.get("field") for a in (t.get("aggs") or [])]
    return [f for f in fields if f]


def apply_filters(df: pd.DataFrame, filters: list[dict[str, Any]] | None) -> pd.DataFrame:
    """Apply the closed filter-op set; a value that can't be coerced raises."""
    out = df
    for flt in filters or []:
        field, op, value = flt["field"], flt["op"], flt.get("value")
        col = out[field]
        if op == "not_null":
            mask = col.notna()
        elif op == "in":
            vals = value if isinstance(value, list) else [value]
            if pdt.is_numeric_dtype(col) and not pdt.is_bool_dtype(col):
                mask = col.isin([float(v) for v in vals])
            else:
                mask = col.astype(str).isin([str(v) for v in vals])
        else:
            if pdt.is_bool_dtype(col):
                target: Any = value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
                left = col
            elif pdt.is_numeric_dtype(col):
                target, left = float(value), col
            elif _is_datetime_like(col):
                target, left = pd.Timestamp(value), _to_datetime(col)
                if left.dt.tz is not None and target.tzinfo is None:
                    target = target.tz_localize(left.dt.tz)
            else:
                target, left = str(value), col.astype(str)
            if op == "eq":
                mask = left == target
            elif op == "ne":
                mask = left != target
            elif op == "gt":
                mask = left > target
            elif op == "gte":
                mask = left >= target
            elif op == "lt":
                mask = left < target
            elif op == "lte":
                mask = left <= target
            else:
                raise ValueError(f"unknown filter op {op!r}")
        out = out[mask.fillna(False)]
    return out


def _agg(series: pd.Series, op: str) -> Any:
    if op not in _AGG_FUNCS:
        raise ValueError(f"unsupported aggregation {op!r}")
    if op in ("min", "max") and not pdt.is_numeric_dtype(series) and _is_datetime_like(series):
        series = _to_datetime(series)
    return series.agg(_AGG_FUNCS[op])


def _json_value(value: Any) -> Any:
    value = _as_jsonable(value)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    return value


def _format_cell(value: Any) -> Any:
    """Preview formatting: floats -> 4 dp, whole floats -> int, NaN -> None."""
    value = _as_jsonable(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        if value == int(value) and abs(value) < 1e15:
            return int(value)
        return round(value, 4)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _fmt_number(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return f"{int(v):,}"
    return f"{v:,.2f}"


def _format_kpi(value: Any, cfg: dict[str, Any]) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return f"{cfg.get('prefix') or ''}{value}{cfg.get('suffix') or ''}"
    fmt = cfg.get("format") or "number"
    prefix, suffix = cfg.get("prefix") or "", cfg.get("suffix") or ""
    v = float(value)
    if fmt == "integer":
        body = f"{round(v):,}"
    elif fmt == "currency":
        body = f"{round(v):,}" if abs(v) >= 1000 else f"{v:,.2f}"
        prefix = prefix or "$"
    elif fmt == "percent":
        # The aggregate is taken to already be in percent units.
        body = f"{v:,.1f}"
        suffix = suffix or "%"
    else:
        body = _fmt_number(v)
    return f"{prefix}{body}{suffix}"


def _auto_grain(ts: pd.Series) -> str:
    valid = ts.dropna()
    if valid.empty:
        return "month"
    span = (valid.max() - valid.min()).days
    if span <= 45:
        return "day"
    if span <= 150:
        return "week"
    if span <= 365 * 8:
        return "month"
    return "year"


def _bucket(ts: pd.Series, grain: str) -> pd.Series:
    """Floor each timestamp to the start of its grain bucket."""
    naive = ts.dt.tz_localize(None) if ts.dt.tz is not None else ts
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return naive.dt.to_period(_PERIOD_FREQ[grain]).dt.start_time


def _bucket_label(ts: pd.Timestamp, grain: str) -> str:
    if grain == "year":
        return f"{ts.year}"
    if grain == "quarter":
        return f"{ts.year}-Q{ts.quarter}"
    if grain == "month":
        return f"{ts.year}-{ts.month:02d}"
    return ts.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# KPI
# --------------------------------------------------------------------------- #


def _compute_kpi(df: pd.DataFrame, widget: dict[str, Any]) -> dict[str, Any]:
    cfg = widget["kpi"]
    frame = apply_filters(df, widget.get("filters"))
    field, op = cfg.get("field"), cfg["agg"]
    if len(frame) == 0:
        value = None
    elif field is None:
        value = _json_value(len(frame))
    else:
        value = _json_value(_agg(frame[field], op))
    caption = "row count" if field is None else f"{op} of {field}"
    return {
        "kind": "kpi",
        "status": "ok",
        "label": widget["title"],
        "value": value,
        "formatted": _format_kpi(value, cfg),
        "format": cfg.get("format") or "number",
        "caption": caption,
    }


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #


def _y_label(y: dict[str, Any]) -> str:
    return "count" if y.get("field") is None else f"{y['agg']} of {y['field']}"


def _agg_by(frame: pd.DataFrame, keys: list[Any], y: dict[str, Any]) -> pd.Series:
    """Group `frame` by key columns/series and aggregate y (count w/o field = size)."""
    grouped = frame.groupby(keys, dropna=True, sort=False)
    if y.get("field") is None:
        return grouped.size()
    return grouped[y["field"]].agg(_AGG_FUNCS[y["agg"]])


def _finish_axis_option(
    kind: str,
    frame: pd.DataFrame,
    names: list[str],
    *,
    area: bool = False,
    single_series: bool = True,
) -> dict[str, Any]:
    """Build the option via the shared Phase 4 builder; rename series to labels."""
    internal = [f"s{i}" for i in range(len(names))]
    data = frame.copy()
    data.columns = ["x"] + internal
    option = _build_echart_option(
        "line" if area else kind, data, x="x", y=internal, series=None, title=None, opts={}
    )
    for s, name in zip(option["series"], names):
        s["name"] = name
        if area:
            s["areaStyle"] = {}
    if single_series:
        option["legend"] = {"show": False}
        option["grid"] = {"left": 8, "right": 24, "top": 24, "bottom": 24, "containLabel": True}
    return _sanitise_option(option)


def _sanitise_option(option: dict[str, Any]) -> dict[str, Any]:
    """Final JSON-safety pass (NaN -> None, numpy -> python) over the whole option."""
    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        return _json_value(v)

    return walk(option)


def _compute_chart(df: pd.DataFrame, widget: dict[str, Any]) -> dict[str, Any]:
    cfg = widget["chart"]
    ctype = cfg["type"]
    frame = apply_filters(df, widget.get("filters"))
    if len(frame) == 0:
        raise ValueError("No rows match this widget's filters.")
    x = cfg["x"]
    limit = int(cfg.get("limit") or 20)

    if ctype == "histogram":
        values = pd.to_numeric(frame[x], errors="coerce").dropna()
        if values.empty:
            raise ValueError(f"Column '{x}' has no numeric values.")
        bins = int(cfg.get("bins") or 20)
        counts, edges = np.histogram(values.to_numpy(dtype=float), bins=bins)
        labels = [f"{edges[i]:.4g} – {edges[i + 1]:.4g}" for i in range(len(counts))]
        out = pd.DataFrame({"x": labels, "s0": counts})
        option = _finish_axis_option("bar", out, ["count"])
        return {"kind": "chart", "status": "ok", "option": option}

    y = cfg.get("y") or {}
    if ctype == "scatter":
        yf = y.get("field")
        pts = pd.DataFrame(
            {
                "x": pd.to_numeric(frame[x], errors="coerce"),
                "s0": pd.to_numeric(frame[yf], errors="coerce"),
            }
        ).dropna()
        if pts.empty:
            raise ValueError("No numeric points to plot.")
        if len(pts) > _MAX_SCATTER_POINTS:
            idx = np.linspace(0, len(pts) - 1, _MAX_SCATTER_POINTS).astype(int)
            pts = pts.iloc[idx]
        option = _build_echart_option(
            "scatter", pts, x="x", y="s0", series=None, title=None, opts={}
        )
        option["series"][0]["name"] = str(yf)
        option["xAxis"]["name"] = str(x)
        option["legend"] = {"show": False}
        option["grid"] = {"left": 8, "right": 24, "top": 24, "bottom": 24, "containLabel": True}
        return {"kind": "chart", "status": "ok", "option": _sanitise_option(option)}

    # bar / line / area / pie: grouped aggregation
    xs = frame[x]
    grain = cfg.get("time_grain")
    time_axis = False
    if ctype in ("line", "area", "bar") and _is_datetime_like(xs):
        ts = _to_datetime(xs)
        grain = grain or _auto_grain(ts)
        key: pd.Series = _bucket(ts, grain)
        time_axis = True
    else:
        grain = None
        key = xs
    work = frame.assign(__key=key.values)

    sort = cfg.get("sort") or ("x_asc" if ctype in ("line", "area") else "y_desc")
    base = _agg_by(work, ["__key"], y).dropna()
    if base.empty:
        raise ValueError("No data to plot after grouping.")
    if sort in ("y_asc", "y_desc"):
        base = base.sort_values(ascending=(sort == "y_asc"), kind="stable").head(limit)
        if time_axis:
            base = base.sort_index()
    else:
        base = base.sort_index(ascending=(sort == "x_asc"))
        base = base.tail(limit) if (time_axis and sort == "x_asc") else base.head(limit)
    kept = list(base.index)

    def label(k: Any) -> Any:
        if time_axis:
            return _bucket_label(pd.Timestamp(k), grain)
        return k if isinstance(k, str) else _as_jsonable(k)

    labels = [label(k) for k in kept]
    series_by = cfg.get("series_by") if ctype in ("bar", "line", "area") else None

    if ctype == "pie":
        out = pd.DataFrame({"x": [str(lab) for lab in labels], "s0": base.to_numpy()})
        option = _build_echart_option(
            "pie", out, x="x", y="s0", series=None, title=None, opts={}
        )
        return {"kind": "chart", "status": "ok", "option": _sanitise_option(option)}

    if series_by:
        cats = work[series_by].astype(str)
        top = list(cats.value_counts().head(_MAX_SERIES).index)
        work = work.assign(__series=cats.where(cats.isin(top), "Other"))
        multi = _agg_by(work, ["__key", "__series"], y).unstack("__series")
        multi = multi.reindex(kept)
        out = pd.DataFrame({"x": labels})
        names: list[str] = []
        for i, col in enumerate(multi.columns):
            out[f"c{i}"] = multi[col].to_numpy()
            names.append(str(col))
        option = _finish_axis_option(
            "bar" if ctype == "bar" else "line",
            out,
            names,
            area=(ctype == "area"),
            single_series=False,
        )
        return {"kind": "chart", "status": "ok", "option": option}

    out = pd.DataFrame({"x": labels, "s0": base.to_numpy()})
    option = _finish_axis_option(
        "bar" if ctype == "bar" else "line",
        out,
        [_y_label(y)],
        area=(ctype == "area"),
    )
    return {"kind": "chart", "status": "ok", "option": option}


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


def _compute_table(df: pd.DataFrame, widget: dict[str, Any]) -> dict[str, Any]:
    cfg = widget["table"]
    frame = apply_filters(df, widget.get("filters"))
    limit = min(int(cfg.get("limit") or 10), _TABLE_MAX_ROWS)
    sort_by = cfg.get("sort_by")
    group_by = cfg.get("group_by") or []

    if group_by:
        grouped = frame.groupby(group_by, dropna=True, sort=False)
        parts: list[pd.Series] = []
        used = set(group_by)
        for agg in cfg.get("aggs") or []:
            field = agg.get("field")
            alias = agg.get("alias") or (
                "count" if field is None else f"{agg['agg']}_{field}"
            )
            base_alias, n = alias, 2
            while alias in used:
                alias, n = f"{base_alias}_{n}", n + 1
            used.add(alias)
            if field is None:
                s = grouped.size()
            else:
                src = frame[field]
                if agg["agg"] in ("min", "max") and not pdt.is_numeric_dtype(src) and _is_datetime_like(src):
                    src = _to_datetime(src)
                s = src.groupby([frame[g] for g in group_by], dropna=True, sort=False).agg(
                    _AGG_FUNCS[agg["agg"]]
                )
            parts.append(s.rename(alias))
        if not parts:
            raise ValueError("Grouped table has no aggregations.")
        result = pd.concat(parts, axis=1).reset_index()
        result.columns = [str(c) for c in result.columns]
        sort_dir = cfg.get("sort_dir") or "desc"
        if sort_by not in result.columns:
            sort_by = result.columns[len(group_by)]
        result = result.sort_values(sort_by, ascending=(sort_dir == "asc"), kind="stable")
    else:
        cols = list(cfg.get("columns") or [])
        result = frame[cols]
        sort_dir = cfg.get("sort_dir") or "asc"
        if sort_by in result.columns:
            result = result.sort_values(sort_by, ascending=(sort_dir == "asc"), kind="stable")

    truncated = len(result) > limit
    result = result.head(limit)
    rows = [[_format_cell(v) for v in rec] for rec in result.itertuples(index=False, name=None)]
    return {
        "kind": "table",
        "status": "ok",
        "columns": [str(c) for c in result.columns],
        "rows": rows,
        "truncated": bool(truncated),
    }


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def compute_widget(df: pd.DataFrame, widget: dict[str, Any]) -> dict[str, Any]:
    """Compute ONE widget; any failure becomes an isolated `status:"error"`."""
    kind = widget.get("kind", "?")
    try:
        missing = [f for f in dict.fromkeys(widget_fields(widget)) if f not in df.columns]
        if missing:
            return {
                "kind": kind,
                "status": "error",
                "message": f"Column '{missing[0]}' no longer exists.",
            }
        if kind == "kpi":
            return _compute_kpi(df, widget)
        if kind == "chart":
            return _compute_chart(df, widget)
        if kind == "table":
            return _compute_table(df, widget)
        return {"kind": kind, "status": "error", "message": f"Unknown widget kind {kind!r}."}
    except Exception as exc:  # noqa: BLE001 — per-widget isolation
        return {"kind": kind, "status": "error", "message": str(exc)[:300] or type(exc).__name__}


def compute_widget_data(df: pd.DataFrame, spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`{widget_id: payload}` for every widget in the spec (never raises)."""
    return {w["id"]: compute_widget(df, w) for w in spec.get("widgets", [])}
