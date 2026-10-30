# Capability: Dashboard Widget Editing, Rebinding and Regenerate (C42)

## What It Does
The user can add, edit and remove individual widgets on an existing dashboard, rebind a widget's fields (including by dragging a dataset column onto it), and regenerate the dashboard from a new natural-language command — all validated against the real columns, with widget edits and rebinds requiring NO LLM call.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| new widget | `{kind, title, kpi\|chart\|table block, description?, filters?}` | `POST /dashboards/{id}/widgets` | no |
| widget patch | `{title?, description?, kpi?\|chart?\|table? (shallow-merged), filters?, bind?: {slot, field, agg?}}` | `PATCH /dashboards/{id}/widgets/{wid}` | no |
| command, mode, keep_title | string (1–1000), `replace`\|`add` (default `replace`), bool | `POST /dashboards/{id}/regenerate` | yes (command) |
| — | — | `POST /dashboards/{id}/restore-previous`, `DELETE …/widgets/{wid}`, `GET …/widgets/{wid}/chart-suggestions` | — |

`bind.slot` ∈ `kpi.field`, `chart.x`, `chart.y`, `chart.series_by`, `table.group_by` (append), `table.agg` (append `{field, agg}`), `table.columns` (append). This is the contract for "drag a field chip onto a widget": the UI picks the slot from the drop zone, the server applies it.

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| updated dashboard + the affected widget's recomputed data | `ok({dashboard, widget_data})` (`regenerate`: `ok({dashboard, data})`) | responses |
| chart suggestions | `[{type, score, rationale, valid}]` ranked by the C41 rule table | `GET …/chart-suggestions` |
| previous spec | one-level snapshot | `dashboards.previous_spec_json` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| LLM via `LLMClient` | ONLY `regenerate` (same single call + ≤1 repair + fallback as C40/C41). Add/edit/remove/rebind/suggestions/restore make zero LLM calls | regenerate falls back deterministically (C40 rules); in `add` mode a fallback adds nothing and returns `generation.notes` |
| disk | load dataset DataFrame; recompute ONLY the touched widget | `500 dashboard_failed` |
| SQLite | update `dashboards` row | `500 write_failed`, rolled back |

## Business Rules
- **Every edit is validated, then applied atomically.** The patched widget is run through the same `validate_spec` widget rules (field existence with case-snap, dtype/agg/axis coherence, clamps). Failure → `400 invalid_widget` with `errors[{code, detail}]` and the stored spec is UNCHANGED. Success → persisted, `updated_at` bumped, only that widget recomputed.
- **Add:** appended at the lowest priority (N+1), placed by first-fit below existing widgets, default size per kind; `description_source="auto"`. Max 12 widgets (`400 too_many_widgets`).
- **Remove:** priorities renumber dense; layout is NOT re-packed (holes allowed; user can click Auto-arrange). Removing the last widget → `400 last_widget`. The dashboard must keep ≥1 widget.
- **Rebind:** `bind` replaces/appends the named slot. If the new binding makes the current chart type invalid (e.g. text field dropped on a `histogram` x), the server returns `400 invalid_widget` with `suggested_chart_types` from the C41 rule table instead of silently changing the type; the UI offers one-click "Switch to <type>". A changed binding regenerates `chart_rationale` and (unless `description_source="user"`) the `description` as deterministic auto text.
- **Edit menu:** title, description (sets `description_source="user"`), chart type, aggregation, x/y/series_by, limit/sort, table columns, widget-level filters, remove.
- **Chart suggestions** are deterministic (C41 rules) and never call the LLM.
- **Regenerate:** `replace` — runs the C41 build pipeline on the same dataset with the new `command`; the old `spec_json` is saved to `previous_spec_json` first; layout is re-assigned; `title` kept when `keep_title` (default true). `add` — runs the pipeline, drops widgets that duplicate an existing widget's bindings, appends the rest (cap 12 total; extras → `generation.dropped_widgets` reason `too_many_widgets`). `command` updated; tokens of the regenerate are added to the row.
- **Restore-previous:** swaps `spec_json` ↔ `previous_spec_json` (so it toggles); `400 nothing_to_restore` when null. Single-widget edits do NOT write `previous_spec_json`.
- Concurrency: last-write-wins per request (single local user); each mutation reads-modifies-writes the spec inside one transaction.
- LLM never writes code (C40 rule); fields are used only as column keys after validation.

## Success Criteria
- [ ] `PATCH …/widgets/{wid}` rebinding a KPI from `revenue` to `units` returns a KPI whose value equals pandas `df.units.sum()` on a 600-row fixture, with ZERO LLM calls (asserted by a call-counting `LLMClient` in the real-key test).
- [ ] Binding a text column to a `sum` KPI → `400 invalid_widget` (`agg_dtype_mismatch`); stored spec byte-identical afterwards.
- [ ] `bind` of a text field onto a `histogram` x → 400 with `suggested_chart_types` containing `bar`.
- [ ] Add widget → 200, widget present with priority N+1, non-overlapping layout, data `status:"ok"`; add beyond 12 → 400 `too_many_widgets`.
- [ ] Remove widget → priorities dense 1..N−1; removing the only widget → `400 last_widget`.
- [ ] `regenerate` (real Gemini) with `mode:"replace"` yields a valid v2 spec reflecting the new command and stores the prior spec; `restore-previous` returns the original spec exactly; `mode:"add"` keeps all original widget ids.
- [ ] Editing a description sets `description_source="user"` and a later rebind keeps the user text.
- [ ] `chart-suggestions` for a datetime x + numeric y ranks `line` first and marks `pie` `valid:false`.
- [ ] UI: "+ Add widget", "⋯" menu (Edit/Change chart/Remove), draggable field chips with drop zones, and "Regenerate…" are real (no "coming later" tags remain except Export).

## Phase
Phase 17. Depends on C41 (spec v2). Extends [dashboard-builder.md](dashboard-builder.md); series assumptions in [dashboard-insights-priority.md](dashboard-insights-priority.md).
