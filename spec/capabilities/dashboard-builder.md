# Capability: Agent-built Dashboard (C40)

## What It Does
Given a dataset (an uploaded or already-imported CSV/Excel/etc. file) and a natural-language command, the agent profiles the data, chooses KPI cards, charts and tables, and returns a VALIDATED dashboard spec that the UI renders as a draggable grid of widgets; the arranged layout is saved.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_id | string | path of `POST /datasets/{id}/dashboards` (a dataset created via C1/C11/C38 upload or an existing one) | yes |
| command | string (1–1000 chars) | request body (the user's natural-language request, e.g. "revenue by region and a monthly trend") | yes |
| title | string (≤80) | request body | no (agent proposes one) |
| layout edits | `[{id,x,y,w,h}]` | `PATCH /dashboards/{id}` (drag-to-rearrange / resize) | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dashboard | `dashboards` row: `{id, dataset_id, title, command, spec, generation}` where `spec` = validated dashboard spec v1 (widgets of kind `kpi`\|`chart`\|`table`, each with field bindings + a grid `layout`) | SQLite (`dashboards`), `POST` response |
| widget data | per-widget computed values: KPI number, ECharts `option` JSON, table rows | `GET /dashboards/{id}/data` (and inline in the `POST` response) |
| generation metadata | `{used_fallback, repaired, supplemented[], dropped_widgets[], notes[], model, tokens_input, tokens_output, duration_ms}` | `dashboards.generation_json` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| LLM via `LLMClient` (Gemini live; stub offline) | ONE structured call (`<node:dashboard>`) returning the spec JSON; at most ONE repair call if validation fails | Any LLM error / unparseable / fully-invalid reply → deterministic **fallback dashboard** built from the data profile (never a 5xx, never an empty dashboard) |
| disk (`uploads/{id}.parquet` / `.csv`) | read the dataset DataFrame (Parquet preferred, CSV fallback — same loader as the ReAct `setup`) | missing/unreadable file → `500 dashboard_failed` (nothing persisted) |
| SQLite | insert/update/delete `dashboards` row | `500 write_failed` (rolled back) |

## Business Rules
- **The LLM never writes or executes code for a dashboard.** It emits a JSON *spec* only. Every widget's data is computed server-side by a fixed, safe pandas aggregation engine driven by that spec (group-by + one of a closed set of aggregation ops). The ReAct loop and the code sandbox (`save_dataset`/`echart`) are NOT used (decision + rationale in `spec/agent.md` → "Dashboard builder pipeline (C40)").
- **Single dataset per dashboard** (v1). A multi-sheet Excel workbook is handled by C38 (one dataset per sheet): the user picks the sheet's dataset.
- **Widget kinds:** `kpi` (one aggregated number), `chart` (`bar|line|area|pie|scatter|histogram`, rendered as ECharts `option` — reuses the Phase 4 option builder `_build_echart_option` for bar/line/scatter/pie, extended server-side for area/histogram), `table` (raw columns or group-by aggregates, ≤50 rows). Dashboard has 1–12 widgets.
- **Aggregation ops (closed set):** `sum|mean|median|min|max|count|nunique` (+ `none` for scatter only). `sum|mean|median` require a numeric field; `min|max` numeric or datetime; `count|nunique` any field (`count` with `field: null` = row count).
- **Strict validation against the real columns** (`validate_spec`): every referenced field must exist in the dataset (an exact match, else a unique case/whitespace-insensitive match is snapped to the real name, else error `unknown_field`); aggregations must be dtype-compatible; chart type/axis roles must be coherent (e.g. `histogram` x numeric, `pie` x categorical with ≤50 distinct → `limit`, `line`/`area` x datetime or ordered); `limit`/`bins`/counts are clamped to the documented ranges; ids are unique; filters use the closed op set `eq|ne|gt|gte|lt|lte|in|not_null`. Full schema in `spec/api.md` → "Dashboard spec v1".
- **Repair then fallback:** if the first reply has validation errors, ONE repair call is made (the error list is appended to the same prompt). After that, any still-invalid widget is DROPPED individually (recorded in `generation.dropped_widgets`). If no widget survives, or the reply is not parseable JSON at all, or the LLM call itself fails (also the offline stub, which returns no JSON), the deterministic fallback dashboard replaces it (`generation.used_fallback=true`) — the UI shows a visible "automatic dashboard" badge so a fallback is never mistaken for an agent choice.
- **Composition guarantee:** a delivered dashboard always has ≥1 `kpi` and ≥1 `chart`; if the validated agent output lacks one of them, the missing kind is supplemented from the deterministic fallback generator (`generation.supplemented`, e.g. `["kpi"]`). A dataset with no numeric and no categorical column still yields a row-count KPI and a table.
- **Layout is server-assigned on creation** (the LLM does not emit coordinates): a 12-column grid, widgets ordered KPIs → charts → tables (LLM order within a kind), default sizes kpi `3×2`, chart `6×5`, table `12×6`, first-fit row-major packing. Contract vector in `spec/api.md`.
- **Layout persistence:** `PATCH /dashboards/{id}` with `layout[]` must name every widget id exactly once, stay within `x≥0, w≥1, x+w≤12, h≥1`, and not overlap (else `400 invalid_layout`). The frontend re-packs after each drop so it always sends a valid layout. Layout survives reload and server restart (stored in `dashboards.spec_json`).
- **Data is computed fresh** on every `GET /dashboards/{id}/data` from the dataset's current file, so a cleaned/re-derived/re-synced dataset is reflected on the next open (the spec itself is not regenerated). If a bound column no longer exists, that widget returns `status:"error"` with a message; the others still render.
- **Per-widget failures are isolated:** one widget's compute error never fails the response or other widgets.
- **Data egress:** the LLM receives the deterministic profile (column names, dtypes, null %, distinct counts, numeric min/max/mean, top-5 categorical values, datetime range), the dataset's compressed notes (`context_facts`, ≤1500 chars) and ≤5 sample rows with cells truncated to 40 chars — same provider egress class as C2/C30; never the full data.
- Deleting a dataset deletes its dashboards (extends C15 — see [dataset-deletion-cascade.md](dataset-deletion-cascade.md)). Deleting a dashboard never touches the dataset.
- LLM tokens for the build are recorded on the `dashboards` row; they are NOT attributed to `query_runs` or `GET /stats/daily` (same accepted gap as C37 starters).
- **Now covered by later capabilities (lifted from the deferred list):** priority ranking + descriptions + chart rationale → [C41](dashboard-insights-priority.md) (Phase 16); dragging fields onto widgets / field rebinding, add/remove/edit widgets, regenerate-from-new-command → [C42](dashboard-widget-editing.md) and dashboard-level filters → [C43](dashboard-filters.md) (Phase 17); save-as-template / reuse on similar data → [C44](dashboard-templates.md) and external read API → [C45](dashboard-external-api.md) (Phase 18); REST API and SQL DB data sources → [C46](api-data-source.md), [C47](sql-data-source.md) (Phase 19). The spec grows from v1 to v2 (v1 stays readable). The "LLM never writes code" rule and the safe aggregation engine are unchanged.
- **Still deferred / out of scope:** multi-dataset dashboards and cross-filtering between widgets, export (PNG/PDF/HTML), **Power BI / Tableau export (explicitly out of scope)**, sharing/multi-user, scheduled refresh, free-form resize beyond the width presets.

## Success Criteria
- [ ] `POST /datasets/{id}/dashboards` with a real command (real Gemini) returns a dashboard whose spec passes `validate_spec`, has ≥1 `kpi` and ≥1 `chart`, and every referenced field exists in the dataset's columns.
- [ ] A KPI `sum` widget's computed value equals the pandas full-data sum of that column (a fixture large enough that a sampled value would differ).
- [ ] Offline/stub provider (no JSON reply) yields a deterministic fallback dashboard with `generation.used_fallback=true`, ≥1 KPI and ≥1 chart, and HTTP 200.
- [ ] A reply referencing a non-existent column is repaired once or the offending widget is dropped; the delivered spec never contains an unknown field (unit-tested with a fake LLM reply).
- [ ] A reply that is non-JSON, empty, or a JSON of the wrong shape never produces a 5xx and never an empty dashboard.
- [ ] `PATCH /dashboards/{id}` with a valid permuted layout persists it (a re-`GET` returns the new coordinates); an overlapping, out-of-bounds, or incomplete layout → `400 invalid_layout` and the stored layout is unchanged.
- [ ] `GET /dashboards/{id}/data` returns an ECharts `option` (with a `series` key) for every `ok` chart widget, and an isolated `status:"error"` (not a 5xx) for a widget whose column was removed.
- [ ] Deleting the dataset removes its dashboards; `DELETE /dashboards/{id}` leaves the dataset intact.
- [ ] In the UI, a user can pick/upload a dataset, type a command, see KPI cards + charts + a table, drag a widget to a new position, reload the page, and see the arrangement preserved.
