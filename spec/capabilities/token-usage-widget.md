# Capability: Token Usage Widget + Daily Stats (C18)

## What It Does
Shows model name, last-query and today's token usage/cost, and storage totals in the sidebar.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| daily stats | JSON | `GET /stats/daily` | yes |
| last run tokens | JSON | `/ask` response | yes |
| dataset totals | JSON | `GET /datasets` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| widget render | UI | sidebar |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| `GET /stats/daily` | aggregate today's completed runs | always 200 |

## Business Rules
- `/stats/daily` aggregates over the server-local day; `context_limit` from a hard-coded model table (unknown → 128000).
- Client-side pricing table computes cost; unknown model → "N/A". THIS is the app's only dollar-cost computation site (`costUsd` in `TokenWidget.tsx`) — the backend never computes cost.
- **Honest discounted cost (C39, Phase 14):** cost uses the cache-discounted formula (rates per-million): `cost_input = (tokens_input − tokens_cached) × rate_in + tokens_cached × rate_in × DISCOUNT`, `cost_output` unchanged. `DISCOUNT` is a per-provider hardcoded constant beside the pricing table — **0.25 for Gemini implicit cache**; non-Gemini models report `tokens_cached=0` this phase so the formula degenerates to the plain arithmetic. The discount applies whether the rate comes from the hardcoded table or the user-configured Settings price (D4) — it is model-keyed, independent of the rate source. Linear, so it applies identically to "Last query" (payload/turn `tokens_cached`, falling back to `/stats/daily`'s `last_tokens_cached` on reload) and "Today" (the daily aggregate `tokens_cached`). See [prompt-cache-accounting.md](prompt-cache-accounting.md).
- **"X of Y from cache" line (C39):** shown for the last query when `tokens_cached > 0` (X = cached, Y = input); hidden at `0` (cold first run / stub — expected, not a bug).
- Storage row = dataset count + total rows.

## Success Criteria
- [ ] After one real run, the widget shows non-zero Last In/Out and Today totals matching `/stats/daily`.
- [ ] An unknown model shows "N/A" cost, not a crash.
- [ ] With `tokens_cached > 0`, the displayed cost is strictly lower than the undiscounted formula would give and the "X of Y from cache" line shows; with `tokens_cached = 0`, the cost equals the plain formula and no cache line renders.
