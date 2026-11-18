"""Dashboard spec v2 — Pydantic models (C40 Phase 15, C41 Phase 16).

The contract is `spec/api.md` -> "Dashboard spec v1" + "Dashboard spec v2".
v1 specs are read as v2 through `upgrade_v1` (lazy, lossless). These models describe the
SHAPE of a *validated* spec (what is persisted in `dashboards.spec_json`). The
semantic checks against the dataset's real columns (field snapping, dtype
compatibility, clamping) live in `graph.dashboard.validate_spec`, which builds
these models from the (untrusted) LLM reply one widget at a time.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GRID_COLUMNS = 12
MAX_WIDGETS = 12

AggOp = Literal["sum", "mean", "median", "min", "max", "count", "nunique"]
ChartAggOp = Literal["sum", "mean", "median", "min", "max", "count", "nunique", "none"]
WidgetKind = Literal["kpi", "chart", "table"]
ChartType = Literal["bar", "line", "area", "pie", "scatter", "histogram"]
FilterOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_null"]
TimeGrain = Literal["day", "week", "month", "quarter", "year"]
ChartSort = Literal["x_asc", "x_desc", "y_asc", "y_desc"]
KpiFormat = Literal["number", "integer", "currency", "percent"]
DescriptionSource = Literal["agent", "auto", "user"]
FilterControl = Literal["select", "multiselect", "range", "date_range"]
SUMMARY_MAX = 200
DESCRIPTION_MAX = 200
RATIONALE_MAX = 140


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Layout(_Model):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=GRID_COLUMNS)
    h: int = Field(ge=1, le=12)


class Filter(_Model):
    field: str
    op: FilterOp
    value: object | None = None


class KpiConfig(_Model):
    field: str | None = None
    agg: AggOp
    format: KpiFormat = "number"
    prefix: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=8)


class YSpec(_Model):
    field: str | None = None
    agg: ChartAggOp


class ChartConfig(_Model):
    type: ChartType
    x: str
    y: YSpec | None = None
    series_by: str | None = None
    time_grain: TimeGrain | None = None
    sort: ChartSort | None = None
    limit: int = Field(default=20, ge=1, le=50)
    bins: int = Field(default=20, ge=5, le=50)


class TableAgg(_Model):
    field: str | None = None
    agg: AggOp
    alias: str | None = None


class TableConfig(_Model):
    columns: list[str] | None = None
    group_by: list[str] | None = None
    aggs: list[TableAgg] | None = None
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] | None = None
    limit: int = Field(default=10, ge=1, le=50)


class Widget(_Model):
    id: str
    kind: WidgetKind
    title: str = Field(min_length=1, max_length=80)
    layout: Layout | None = None
    filters: list[Filter] = Field(default_factory=list, max_length=5)
    kpi: KpiConfig | None = None
    chart: ChartConfig | None = None
    table: TableConfig | None = None
    # --- v2 (C41) ---
    priority: int = Field(default=1, ge=1)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    description_source: DescriptionSource = "auto"
    chart_rationale: str | None = Field(default=None, max_length=RATIONALE_MAX)
    ignore_dashboard_filters: bool = False  # Phase 17 (C43)


class DashboardFilter(_Model):
    """Dashboard-level filter control (Phase 17, C43); shape only."""

    id: str
    field: str
    control: FilterControl
    value: object | None = None


class DashboardSpec(_Model):
    version: Literal[1, 2] = 2
    title: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX)
    filters: list[DashboardFilter] = Field(default_factory=list, max_length=5)
    widgets: list[Widget] = Field(min_length=1, max_length=MAX_WIDGETS)


def _basic_caption(w: dict[str, Any]) -> str:
    """Minimal deterministic caption used only for the v1 -> v2 upgrade."""
    kind = w.get("kind")
    if kind == "kpi":
        k = w.get("kpi") or {}
        f, agg = k.get("field"), k.get("agg")
        text = "Number of rows." if not f else f"{agg} of {f} across all rows."
    elif kind == "chart":
        c = w.get("chart") or {}
        y = c.get("y") or {}
        what = f"{y.get('agg')} of {y['field']}" if y.get("field") else "row count"
        text = f"{what} by {c.get('x')}."
    else:
        text = "Table preview of the data."
    return text[:DESCRIPTION_MAX]


def upgrade_v1(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a v2 copy of a stored spec. Idempotent; never mutates the input.

    priority = row-major reading order of the stored layout (y, x); widgets
    without a layout keep list order after laid-out ones; description = auto
    caption; summary = None.
    """
    out = dict(spec)
    widgets = [dict(w) for w in spec.get("widgets", [])]
    if spec.get("version") == 2 and all(isinstance(w.get("priority"), int) for w in widgets):
        out["widgets"] = widgets
        return out

    def key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        i, w = item
        lay = w.get("layout")
        if isinstance(lay, dict):
            return (0, int(lay.get("y", 0)), int(lay.get("x", 0)), i)
        return (1, 0, 0, i)

    for rank, (_, w) in enumerate(sorted(enumerate(widgets), key=key), start=1):
        w["priority"] = rank
        if not w.get("description"):
            w["description"] = _basic_caption(w)
            w["description_source"] = "auto"
        else:
            w.setdefault("description_source", "agent")
        w.setdefault("ignore_dashboard_filters", False)
    out["version"] = 2
    out.setdefault("summary", None)
    out.setdefault("filters", [])
    out["widgets"] = widgets
    return out
