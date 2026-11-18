"""Deterministic data profile for the dashboard builder (C40, Phase 15).

Zero LLM. `profile_dataframe(df, notes)` inspects the FULL frame (vectorised,
cheap) and returns a dict with per-column `{name, dtype_alias, role, null_pct,
nunique, stats}`, a few truncated sample rows, the `columns_schema`
(name -> dtype alias) the validator uses, and a compact JSON `text` (<= budget)
for the prompt. Roles: measure | dimension | time | id | text.
"""
from __future__ import annotations

import json
import re
import warnings
from typing import Any

import pandas as pd
from pandas.api import types as pdt

MAX_PROFILED_COLUMNS = 60
MAX_SAMPLE_ROWS = 5
MAX_CELL_CHARS = 40
PROFILE_TEXT_BUDGET = 6000
_DATE_SAMPLE = 300
_DATE_RATIO = 0.95

_ID_HINT_RE = re.compile(r"(^|[^a-z])(id|key|code|uuid)([^a-z]|$)")


def looks_like_dates(series: pd.Series) -> bool:
    """True when an object/text column parses as dates for >= 95% of its values."""
    if pdt.is_datetime64_any_dtype(series):
        return True
    if pdt.is_bool_dtype(series) or pdt.is_numeric_dtype(series):
        return False
    sample = series.dropna()
    if sample.empty:
        return False
    if len(sample) > _DATE_SAMPLE:
        sample = sample.sample(_DATE_SAMPLE, random_state=0)
    values = [v for v in sample.tolist()]
    # Only strings that contain a digit and are not tiny can be dates.
    if not all(isinstance(v, str) and len(v) >= 6 and any(c.isdigit() for c in v) for v in values):
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(pd.Series(values), errors="coerce", format="mixed")
    except Exception:  # noqa: BLE001 — undetectable -> not a date column
        return False
    return float(parsed.notna().mean()) >= _DATE_RATIO


def dtype_alias(series: pd.Series) -> str:
    """Stable dtype alias: integer|float|boolean|datetime|category|text|duration."""
    if pdt.is_bool_dtype(series):
        return "boolean"
    if pdt.is_datetime64_any_dtype(series):
        return "datetime"
    if pdt.is_timedelta64_dtype(series):
        return "duration"
    if pdt.is_integer_dtype(series):
        return "integer"
    if pdt.is_numeric_dtype(series):
        return "float"
    if isinstance(series.dtype, pd.CategoricalDtype):
        return "category"
    if looks_like_dates(series):
        return "datetime"
    return "text"


def columns_schema_for(df: pd.DataFrame) -> dict[str, str]:
    """name -> dtype alias for every column (used by `validate_spec`)."""
    return {str(c): dtype_alias(df[c]) for c in df.columns}


def _trunc(value: Any, limit: int = MAX_CELL_CHARS) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _num(value: Any) -> float | int | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return int(f) if f == int(f) and abs(f) < 1e15 else round(f, 4)


def _role(name: str, alias: str, series: pd.Series, nunique: int, rows: int) -> str:
    ratio = nunique / rows if rows else 0.0
    if alias == "datetime":
        return "time"
    if _ID_HINT_RE.search(name.lower()) and ratio > 0.9:
        return "id"
    if alias in ("integer", "float"):
        if alias == "integer" and nunique <= 10 and rows > 2 * nunique:
            return "dimension"
        return "measure"
    if alias in ("boolean", "category"):
        return "dimension"
    if alias == "text":
        non_null = series.dropna()
        avg_len = float(non_null.astype(str).str.len().mean()) if len(non_null) else 0.0
        if ratio > 0.5 and avg_len > 40:
            return "text"
        return "dimension"
    return "dimension"


def _column_profile(df: pd.DataFrame, col: Any) -> dict[str, Any]:
    series = df[col]
    name = str(col)
    rows = len(df)
    alias = dtype_alias(series)
    nunique = int(series.nunique(dropna=True))
    role = _role(name, alias, series, nunique, rows)
    null_pct = round(float(series.isna().mean()) * 100, 1) if rows else 0.0
    stats: dict[str, Any] = {}
    if alias in ("integer", "float"):
        stats = {
            "min": _num(series.min()),
            "max": _num(series.max()),
            "mean": _num(series.mean()),
            "sum": _num(series.sum()),
        }
    elif alias == "datetime":
        parsed = series if pdt.is_datetime64_any_dtype(series) else pd.to_datetime(
            series, errors="coerce", format="mixed"
        )
        lo, hi = parsed.min(), parsed.max()
        stats = {
            "min": None if pd.isna(lo) else lo.isoformat()[:10],
            "max": None if pd.isna(hi) else hi.isoformat()[:10],
        }
    else:
        top = series.dropna().astype(str).value_counts().head(5)
        stats = {"top": [[_trunc(k), int(v)] for k, v in top.items()]}
    return {
        "name": name,
        "dtype_alias": alias,
        "role": role,
        "null_pct": null_pct,
        "nunique": nunique,
        "stats": stats,
    }


def _render_text(
    rows: int,
    columns: list[dict[str, Any]],
    extra: list[str],
    samples: list[dict[str, str]],
    cols_total: int,
) -> str:
    payload: dict[str, Any] = {
        "rows": rows,
        "columns_total": cols_total,
        "columns": [
            {
                "name": c["name"],
                "type": c["dtype_alias"],
                "role": c["role"],
                "null_pct": c["null_pct"],
                "distinct": c["nunique"],
                "stats": c["stats"],
            }
            for c in columns
        ],
    }
    if extra:
        payload["other_columns"] = extra
    if samples:
        payload["sample_rows"] = samples
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def profile_dataframe(df: pd.DataFrame, notes: str = "") -> dict[str, Any]:
    """Profile the FULL frame. Never raises on odd data; deterministic."""
    all_cols = list(df.columns)
    columns = [_column_profile(df, c) for c in all_cols[:MAX_PROFILED_COLUMNS]]
    extra = [
        f"{c} ({dtype_alias(df[c])})" for c in all_cols[MAX_PROFILED_COLUMNS:]
    ]
    schema = {c["name"]: c["dtype_alias"] for c in columns}
    for c in all_cols[MAX_PROFILED_COLUMNS:]:
        schema[str(c)] = dtype_alias(df[c])

    samples: list[dict[str, str]] = []
    for _, rec in df.head(MAX_SAMPLE_ROWS).iterrows():
        samples.append({str(k): _trunc(v) for k, v in rec.items()})

    # Shrink to fit the prompt budget: drop samples first, then trim the stats of
    # trailing columns, then move trailing columns to the name-only list.
    shown = list(columns)
    spill = list(extra)
    use_samples = list(samples)
    text = _render_text(len(df), shown, spill, use_samples, len(all_cols))
    if len(text) > PROFILE_TEXT_BUDGET:
        use_samples = []
        text = _render_text(len(df), shown, spill, use_samples, len(all_cols))
    while len(text) > PROFILE_TEXT_BUDGET and len(shown) > 5:
        cut = max(1, len(shown) // 10)
        moved = shown[-cut:]
        shown = shown[:-cut]
        spill = [f"{c['name']} ({c['dtype_alias']})" for c in moved] + spill
        text = _render_text(len(df), shown, spill, use_samples, len(all_cols))
    if len(text) > PROFILE_TEXT_BUDGET:
        text = text[:PROFILE_TEXT_BUDGET]

    return {
        "row_count": int(len(df)),
        "col_count": int(len(all_cols)),
        "columns": columns,
        "other_columns": extra,
        "sample_rows": samples,
        "columns_schema": schema,
        "text": text,
        "notes": notes or "",
    }
