# Capability: Dashboard Templates and Schema-bound Reuse (C44)

## What It Does
A dashboard can be saved as a TEMPLATE (its spec plus the schema of columns it requires, with dtype classes) and later applied to any other dataset with the same schema — a new file, a refreshed DB/API snapshot — with explicit binding validation and NO LLM call.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dashboard_id, name (1–80), description? (≤300) | path + body | `POST /dashboards/{id}/template` | yes (name) |
| template_id, dataset_id | path + body | `POST /templates/{id}/validate`, `POST /templates/{id}/apply` | yes |
| mapping | `{required_column: target_column}` the user confirmed | same bodies | no |
| title?, replace_dashboard_id? | string, id | `apply` body | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| template | `dashboard_templates` row: `{id, name, description, spec, required_schema[], source_dashboard_id, created_at, updated_at}` | `/templates*` responses |
| binding report | `{ok, bindings[{required, dtype_class, status: exact\|snapped\|mapped\|suggested\|missing\|incompatible, target, target_dtype, candidates[]}], missing[], incompatible[], suggestions[], extra_columns[]}` | `validate` + the `422` body of `apply` |
| new dashboard | a normal `dashboards` row (`template_id` set, `command` = "Template: <name>") + inline widget data | `apply` response |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| disk | load the target dataset's columns/dtypes (and frame for the data compute) | `500 dashboard_failed` |
| SQLite | insert template / dashboard | `500 write_failed`, rolled back |

**No LLM call anywhere in this capability.**

## Business Rules
- **Required schema** is derived from the dashboard spec when saving: every column referenced by any widget (`kpi.field`, chart `x/y/series_by`, table `columns/group_by/aggs`, widget filters, dashboard filters) → `{name, dtype_class: numeric|datetime|categorical, roles: ["kpi.field","chart.x",…]}` using the source dataset's `columns_schema` (alias → class, per the dtype table in `spec/data.md`). Row-count-only KPIs (`field:null`) need no column. The template stores the spec with its layout and priorities as-is.
- **Binding algorithm (`bind_schema(required, target_schema, mapping=None)`, pure function in `src/graph/dashboard_templates.py`)**, per required column in order: (1) `mapping[required]` if given and the target exists → `mapped`; (2) exact name → `exact`; (3) unique case/whitespace/underscore-insensitive match → `snapped`; (4) otherwise `missing`, with up to 3 `candidates` by normalised-token equality or `difflib` ratio ≥ 0.75 among unbound target columns of a compatible dtype class → status `suggested` when ≥1 candidate (NOT applied). Then dtype check: target class must equal required class, except integer/float interchangeable and `categorical` accepting `boolean/category/text`; a text column bound to a numeric requirement is `incompatible` (no coercion). Two required columns may not bind to the same target (second → `missing` with a note).
- **`ok` = no `missing`, `suggested` or `incompatible` entries left.** `extra_columns` (target columns unused) are informational.
- **Apply** = bind → rewrite every field reference via the final binding map → `validate_spec` (must pass; else `422 binding_mismatch` with the report) → create dashboard (layout/priority preserved; texts kept; `description_source` unchanged; `chart_rationale` kept) → compute data. If `replace_dashboard_id` is given and that dashboard is bound to the same template, its `dataset_id` and `spec_json` are updated in place (one-level `previous_spec_json` kept). Zero LLM calls (asserted in tests).
- **`validate`** performs the same binding without persisting anything (dry run for the UI preview).
- **Suggestions never auto-apply**: only an explicit `mapping` from the client resolves a `suggested` status.
- **Threshold rules:** if the target dataset has 0 rows → `400 empty_dataset`. If fewer than all required columns bind → `422`, nothing created.
- Templates are independent of their source dashboard/dataset (deleting either leaves the template). Deleting a template leaves dashboards created from it. Renaming via `PATCH /templates/{id}`.
- **Applies to any dataset regardless of origin**: uploaded files, refreshed DB/API snapshots (C46/C47), derived datasets. "Same DB / same API" reuse = refresh the source dataset (C46/C47) then apply, or apply to the refreshed dataset's existing dashboards (they recompute on open).
- Binding report is also returned by C46/C47 `refresh` for dashboards bound to the refreshed dataset (`schema_diff` + `binding_status`).

## Success Criteria
- [ ] Saving a dashboard referencing `region, revenue, order_date, customer_id` stores exactly those 4 required columns with correct dtype classes.
- [ ] Apply to a second 600-row dataset with identical schema but different values creates a dashboard whose KPI `sum(revenue)` equals pandas on THAT dataset (and differs from the source's), with zero LLM calls.
- [ ] A target with header `Region` / `Revenue ` binds as `snapped`; apply succeeds.
- [ ] A target missing `units` → `422 binding_mismatch`, `missing:["units"]`, no dashboard created.
- [ ] A target where `revenue` is renamed `revenue_usd` → `validate` reports `suggested` with candidate `revenue_usd`; apply WITHOUT mapping → 422; apply WITH `mapping:{revenue:"revenue_usd"}` → success.
- [ ] A target where `revenue` is text → `incompatible`, not coerced, 422.
- [ ] `replace_dashboard_id` updates the existing dashboard in place and keeps its id.
- [ ] Deleting the source dataset and dashboard leaves the template usable.
- [ ] UI: "Save as template", a Templates list, "Apply to dataset…" with a binding-review step (green exact/snapped rows, amber suggestions with a dropdown to confirm, red missing/incompatible), Apply disabled until `ok`.

## Phase
Phase 18. Depends on C41/C42 (spec v2). See [dashboard-insights-priority.md](dashboard-insights-priority.md) for series assumptions.
