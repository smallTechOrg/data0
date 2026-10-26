"""Dashboard spec v1 — Pydantic models (C40, Phase 15).

The contract is `spec/api.md` -> "Dashboard spec v1". These models describe the
SHAPE of a *validated* spec (what is persisted in `dashboards.spec_json`). The
semantic checks against the dataset's real columns (field snapping, dtype
compatibility, clamping) live in `graph.dashboard.validate_spec`, which builds
these models from the (untrusted) LLM reply one widget at a time.
"""
from __future__ import annotations

from typing import Literal

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


class DashboardSpec(_Model):
    version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    widgets: list[Widget] = Field(min_length=1, max_length=MAX_WIDGETS)
