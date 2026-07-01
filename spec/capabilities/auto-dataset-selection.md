# Capability: Automatic Dataset Selection (C19)

## What It Does
The agent itself picks which datasets to use for a question — there is no pre-flight selector and no manual scoping. `setup` builds a metadata-only *catalog* of ALL workspace datasets and injects it into the ReAct prompt; the agent references whichever datasets the question needs and they are **lazily loaded** on first reference. Only the datasets it actually touches are materialized and recorded on the run.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| question | string | `/ask` | yes |
| dataset catalog | list | DB (`{id, filename, alias, columns, notes}` per dataset, no frames read) | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| loaded dataset_ids | list | run `dataset_ids_json` + session set (only the datasets the agent LOADED) |
| derived dataset_ids | list | session set (datasets the agent created via `save_dataset`) |

## Mechanism
- `setup` reads each candidate `DatasetRow` and renders a catalog line per dataset (`` `df1` (alias `sales`) — sales.csv: col1, col2 `` + optional compressed notes). Columns come from `columns_json`; notes come ONLY from cached `context_facts` (C31) — raw notes are never sent (C31). No frames are read here.
- The sandbox namespace is **lazy** (`build_lazy_namespace`): `df`/`df1`/`df2`/…/`<alias>` resolve to their DataFrame the first time the agent references one, loading on demand (via the session frame cache C27 when in a session), caching for the run, and recording the id in `_loaded_ids[run_id]`.
- After the run, `run_agent` records ONLY the loaded ids on the `query_runs` row (`get_loaded_ids`), so the C15 cascade-delete tracks real dependencies (deleting a dataset only cascades to runs/sessions that actually used it).

## External Calls
None specific to selection — the choice is made by the per-iteration `plan_action` LLM call inside the graph (no separate selector call).

## Business Rules
- Every `/ask` receives ALL workspace datasets as the catalog; a `no_datasets` **400** is returned when the workspace is empty.
- The client cannot scope the run: legacy `dataset_id`/`dataset_ids` request fields are accepted for API compatibility but IGNORED.
- A session does not own a frozen dataset set — each turn (including follow-ups) re-picks from the full catalog; the session set accumulates the datasets the agent USED plus any it DERIVED.
- `selector_reasoning` is retained (payload + `query_runs` column) for backward compatibility but is always `null`/NULL.
- Stub provider: its first `<node:plan>` action is `df.describe().to_string()`, which loads the first catalog dataset via `df` (recorded in the used-set).

## Success Criteria
- [ ] With three datasets and a question about one, the agent loads only the relevant dataset and the run's `dataset_ids_json` contains just that id (real Gemini).
- [ ] The catalog lists every dataset but reads no frames in `setup` (metadata-only).
- [ ] Deleting a dataset cascades only to runs/sessions that actually loaded it (C15).
