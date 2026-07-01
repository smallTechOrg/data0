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
- `setup` reads each candidate `DatasetRow` and renders a LEAN catalog line per dataset (+ optional compressed notes). By default the line lists every column, exactly as a plain schema would (`` `df1` (alias `sales`) — sales.csv: product, price, qty ``). For a wide table it is instead rendered as the column COUNT + a PREVIEW of the first `_CATALOG_COLUMN_PREVIEW` names from `columns_json` + a `(+K more)` pointer (`` `df1` (alias `events`) — events.csv — 28 cols: user, session, ts, device, os, browser, … (+22 more — `df1.columns` for all) ``) — but **only when that compressed form is shorter than listing every column** (so a barely-wide table with short names still lists them all). The catalog is therefore **never larger than a plain column listing, and collapses hard for the wide tables that dominate a big workspace's per-iteration prompt cost**; the agent pulls the full columns on demand (`df1.columns.tolist()`) for the datasets it drills into (C33 token economics). Notes come ONLY from cached `context_facts` (C31) — raw notes are never sent (C31). No frames are read here.
- The sandbox namespace is **lazy** (`build_lazy_namespace`): `df`/`df1`/`df2`/…/`<alias>` resolve to their DataFrame the first time the agent references one, loading on demand (via the session frame cache C27 when in a session), caching for the run, and recording the id in `_loaded_ids[run_id]`.
- After the run, `run_agent` records ONLY the loaded ids on the `query_runs` row (`get_loaded_ids`), so the C15 cascade-delete tracks real dependencies (deleting a dataset only cascades to runs/sessions that actually used it).

## External Calls
None specific to selection — the choice is made by the per-iteration `plan_action` LLM call inside the graph (no separate selector call).

## Business Rules
- Every `/ask` receives ALL workspace datasets as the catalog; a `no_datasets` **400** is returned when the workspace is empty.
- The catalog is ordered by upload time (oldest first), so its `df1`/`df2`/… numbering is deterministic and stable across turns and mirrors the order the user added the tables. (Without an explicit order, `select(id)` returns rows in random UUID order and `df1` would point at an arbitrary table each run.)
- The client cannot scope the run: legacy `dataset_id`/`dataset_ids` request fields are accepted for API compatibility but IGNORED.
- A session does not own a frozen dataset set — each turn (including follow-ups) re-picks from the full catalog; the session set accumulates the datasets the agent USED plus any it DERIVED.
- `selector_reasoning` is retained (payload + `query_runs` column) for backward compatibility but is always `null`/NULL.
- Stub provider: its first `<node:plan>` action is `df.describe().to_string()`, which loads the first catalog dataset via `df` (recorded in the used-set).

## Success Criteria
- [ ] With three datasets and a question about one, the agent loads only the relevant dataset and the run's `dataset_ids_json` contains just that id (real Gemini).
- [ ] The catalog lists every dataset but reads no frames in `setup` (metadata-only).
- [ ] Deleting a dataset cascades only to runs/sessions that actually loaded it (C15).
