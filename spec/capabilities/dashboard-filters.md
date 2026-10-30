# Capability: Dashboard-level Filters (C43)

## What It Does
A dashboard can carry filter controls (pick categories, a numeric range, or a date range on a column) that narrow the data of every widget at once, without any LLM call.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| filter definitions | `[{id, field, control: "select"\|"multiselect"\|"range"\|"date_range", value?}]` (≤5) | `PATCH /dashboards/{id}` `{filters}` | no |
| ad-hoc override | JSON `[{id, value}]` (≤2000 chars) | `GET /dashboards/{id}/data?filters=` | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| `spec.filters` | defaults persisted in the spec | `spec_json` |
| `data.filter_options` | per filter: `select/multiselect` → `{values: [≤100 distinct, with counts], truncated}`; `range` → `{min, max}`; `date_range` → `{min, max}` ISO | `GET …/data` |
| `data.filters_applied`, `data.row_count_filtered` | echo of effective filters and rows left | `GET …/data` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| disk | dataset frame (filter options computed on the UNFILTERED frame) | `500 dashboard_failed` |

No LLM. No other system.

## Business Rules
- Filters map to the closed C40 op set: `select` → `eq`, `multiselect` → `in`, `range` → `gte`+`lte`, `date_range` → `gte`+`lte` on a datetime column. Dashboard filters are AND-combined with each widget's own `filters`.
- A filter's field must exist and its control must fit the dtype (`range` numeric only, `date_range` datetime only, `select/multiselect` categorical/low-cardinality ≤ 500 distinct); else `400 invalid_filter`. Empty `value` = inactive (all rows).
- A widget may set `ignore_dashboard_filters: true` (e.g. a "company total" KPI); the edit menu exposes it.
- Override via `?filters=` is non-persistent (used by the UI as the user toggles and by external apps); `PATCH {filters}` persists defaults. Filters that match zero rows yield empty widgets (`KPI "—"`, empty chart with an "No data for current filters" note), never errors.
- A bound column removed from the dataset → that filter reports `status:"error"` and is ignored for other widgets (isolated failure, like C40).
- Template (C44) schema includes filter fields as required columns.

## Success Criteria
- [ ] With `region = North` applied, a KPI `sum(revenue)` equals pandas `df[df.region=="North"].revenue.sum()` (600-row fixture) and differs from the unfiltered value.
- [ ] `?filters=` override changes data but not the stored spec; `PATCH {filters}` persists and survives reload.
- [ ] A `range` filter on a text column → `400 invalid_filter`; a filter on a missing column → `400 invalid_filter`.
- [ ] `filter_options` for `region` lists exactly its distinct values with counts that sum to the row count.
- [ ] A widget with `ignore_dashboard_filters` keeps its unfiltered value while others change.
- [ ] Zero-row filter → HTTP 200, KPI `value:null`, no widget `error`.
- [ ] UI: filter bar above the grid with controls per filter; changing a control updates all widgets in one refetch; "Reset" clears.

## Phase
Phase 17. Spec in [dashboard-insights-priority.md](dashboard-insights-priority.md) (series assumptions). Extends [dashboard-builder.md](dashboard-builder.md).
