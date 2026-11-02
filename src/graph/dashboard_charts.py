"""Chart-type selection rules — single source of truth (C41, Phase 16).

Used by (a) the prompt guidance, (b) the validator's clamp, (c) the fallback
generator, (d) C42's chart suggestions. Pure functions over column profile
dicts as produced by `graph.dashboard_profile` (`name`, `dtype_alias`, `role`,
`nunique`); no I/O, no LLM.
"""
from __future__ import annotations

from typing import Any

PIE_MAX_CATEGORIES = 8
BAR_MAX_CATEGORIES = 50
RATIONALE_MAX = 140
SERIES_TYPES = ("bar", "line", "area")  # chart types that accept series_by
ORDERED_TYPES = ("line", "area")  # need an ordered x

# Human-readable table, rendered into the prompt and consulted by `suggest`.
CHART_RULES: list[dict[str, str]] = [
    {"id": "time_measure", "when": "time x + measure", "chart": "line",
     "note": "area if cumulative-looking or few series"},
    {"id": "cat_small_whole", "when": "categorical x <= 8 distinct + measure, parts-of-whole intent",
     "chart": "pie", "note": "otherwise bar"},
    {"id": "cat_small", "when": "categorical x <= 8 distinct + measure", "chart": "bar",
     "note": "sorted"},
    {"id": "cat_large", "when": "categorical x 9-50 distinct", "chart": "bar",
     "note": "sorted, top-N limit"},
    {"id": "two_numeric", "when": "two numeric columns", "chart": "scatter", "note": ""},
    {"id": "distribution", "when": "single numeric distribution", "chart": "histogram",
     "note": ""},
    {"id": "series_by", "when": "series_by", "chart": "bar|line|area",
     "note": "only on these chart types"},
    {"id": "clamp_pie", "when": f"pie with > {PIE_MAX_CATEGORIES} categories", "chart": "bar",
     "note": "hard clamp"},
    {"id": "clamp_ordered", "when": "line/area on a non-ordered x", "chart": "bar",
     "note": "hard clamp"},
]


def rules_text() -> str:
    """Compact rendering of CHART_RULES for the LLM prompt."""
    lines = []
    for r in CHART_RULES:
        tail = f" ({r['note']})" if r["note"] else ""
        lines.append(f"- {r['when']} -> {r['chart']}{tail}")
    return "\n".join(lines)


def _cols(profile: Any) -> list[dict[str, Any]]:
    if isinstance(profile, dict):
        return list(profile.get("columns", []))
    return list(profile or [])


def find_column(profile: Any, name: str | None) -> dict[str, Any] | None:
    if name is None:
        return None
    for c in _cols(profile):
        if c.get("name") == name:
            return c
    low = str(name).strip().lower()
    for c in _cols(profile):
        if str(c.get("name", "")).strip().lower() == low:
            return c
    return None


def is_ordered(col: dict[str, Any] | None) -> bool:
    """x is ordered when it is a datetime or a numeric column."""
    if not col:
        return False
    return col.get("dtype_alias") in ("datetime", "integer", "float") or col.get("role") == "time"


def _is_numeric(col: dict[str, Any] | None) -> bool:
    return bool(col) and col.get("dtype_alias") in ("integer", "float")


def clamp_chart_type(
    chart_type: str,
    x_col: dict[str, Any] | None,
    *,
    limit: int | None = None,
    series_by: str | None = None,
) -> tuple[str, str | None]:
    """Apply the hard clamps. Returns (chart_type, note|None).

    pie with > 8 categories -> bar; line/area on a non-ordered x -> bar.
    `limit` caps the effective pie category count (top-N). `series_by` is
    accepted for signature stability; dropping series on non-series types is the
    validator's job.
    """
    if x_col is None:
        return chart_type, None
    if chart_type == "pie":
        n = int(x_col.get("nunique") or 0)
        if limit:
            n = min(n, limit)
        if n > PIE_MAX_CATEGORIES:
            return "bar", (
                f"Pie chart on '{x_col.get('name')}' has {n} categories "
                f"(max {PIE_MAX_CATEGORIES}); converted to bar."
            )
    if chart_type in ORDERED_TYPES and not is_ordered(x_col):
        return "bar", (
            f"{chart_type.capitalize()} chart needs an ordered x; "
            f"'{x_col.get('name')}' is not ordered, converted to bar."
        )
    return chart_type, None


def suggest(
    x_col: dict[str, Any] | None,
    y_col: dict[str, Any] | None = None,
    *,
    parts_of_whole: bool = False,
) -> list[str]:
    """Dtype-valid chart types for the binding, best first (never empty)."""
    if x_col is None:
        return ["bar"]
    n = int(x_col.get("nunique") or 0)
    if x_col.get("dtype_alias") == "datetime" or x_col.get("role") == "time":
        return ["line", "area", "bar"]
    if _is_numeric(x_col) and _is_numeric(y_col) and x_col.get("role") != "dimension":
        return ["scatter", "line", "bar"]
    if _is_numeric(x_col) and y_col is None:
        return ["histogram", "bar"]
    if n <= PIE_MAX_CATEGORIES:
        return ["pie", "bar"] if parts_of_whole else ["bar", "pie"]
    return ["bar"]


def rationale_for(chart: dict[str, Any], profile: Any) -> str:
    """Deterministic, data-citing chart justification (<= 140 chars)."""
    ctype = chart.get("type", "bar")
    x = find_column(profile, chart.get("x"))
    xname = chart.get("x")
    n = int(x.get("nunique") or 0) if x else 0
    y = chart.get("y") or {}
    yname = y.get("field")
    if ctype in ("line", "area"):
        text = f"{xname} is ordered, so a {ctype} shows the trend over it."
    elif ctype == "pie":
        text = f"{xname} has only {n} categories, so a pie shows each share of the whole."
    elif ctype == "scatter":
        text = f"Two numeric fields ({xname}, {yname}); a scatter reveals their relationship."
    elif ctype == "histogram":
        text = f"{xname} is numeric; a histogram shows how its values are distributed."
    elif n > PIE_MAX_CATEGORIES:
        text = f"{xname} has {n} categories; a sorted bar compares them (top {chart.get('limit', 20)})."
    elif n:
        text = f"{xname} is categorical; bars compare its {n} values side by side."
    else:
        text = f"{xname} is categorical; bars compare its values side by side."
    return text[:RATIONALE_MAX]
