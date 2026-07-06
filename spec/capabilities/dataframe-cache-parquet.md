# Capability: Session-scoped DataFrame Cache + Parquet (C27)

## What It Does
Caches loaded DataFrames per session (LRU, ~1GB) and pre-converts uploads to Parquet for fast loads.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_ids, session_id | list/string | `setup` | yes |
| Parquet/CSV files | files | `uploads/` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| in-memory DataFrames | objects | cache / run-scoped dict |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| disk | read Parquet (preferred) / CSV (fallback) | fatal → handle_error |

## Business Rules
- Session runs use a session-keyed cache with LRU eviction (~1GB budget) + touch-on-hit.
- Single-turn runs use a run-scoped `_dataframes[run_id]` dict, released at finalize.
- Parquet is written at upload time (C1) and preferred on load.
- **Per-turn isolation (Phase 11):** the cache never hands out the stored frame object itself — each turn receives an isolated snapshot (a near-zero-cost copy-on-write shallow copy, on both hit and miss paths). In-place mutations by one turn's code never change what later turns see; the cached original keeps its on-disk dtypes/values until invalidation.
- Within a single run, the loaded frame object is shared across that run's steps (intra-run mutations remain self-visible) — isolation is per-turn, not per-step.

## Success Criteria
- [ ] A second question in the same session reuses the cached DataFrame (no re-read), verifiable by faster setup / a cache-hit log.
- [ ] Loading prefers Parquet; a missing Parquet falls back to CSV without error.
- [ ] Turn 1 mutates a loaded frame's column dtype in place; a fresh load for the same session/dataset (turn 2) returns the ORIGINAL dtype while still logging a cache hit (no disk re-read).
