# Capability: Prompt-cache Token Accounting (C39)

## What It Does
Captures Gemini's implicit-cache hit count (`cached_content_token_count`) per LLM call, accumulates and persists it per run as `tokens_cached`, and surfaces "X of Y tokens served from cache" plus an honest, cache-discounted cost in the token widgets — correcting a cost display that today OVERSTATES real spend.

## Measured Ground Truth (Step-0 spike, run 2026-07-08 — DONE, do not re-derive)

Three real `gemini-3.1-flash-lite` calls with a byte-identical ~16.5K-token prefix and only the tail differing (the ReAct loop's exact shape: `[tag, datasets, memory, history, question]` with a growing tail):

- call 1 (cold): `prompt_token_count=16502`, `cached_content_token_count=None` (absent → 0)
- calls 2 & 3: `prompt_token_count=16502`, `cached_content_token_count=12265` — **~74% of the prompt served from implicit cache on every post-first call**

**Conclusion:** implicit caching is ALREADY ACTIVE for this model — no explicit `CachedContent` API work is needed; the backlog's fork resolves to "Lever 1 collapses to honest accounting." Also confirmed: today's cost display OVERSTATES real spend — it prices all input tokens at the full rate while ~74% are billed at the implicit-cache discount on iterations 2+. Nuance: a fully cold single-iteration run legitimately has `tokens_cached=0` — correct behavior, not a failure.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| `usage_metadata.cached_content_token_count` | int \| absent | each Gemini `generate_content` response (already returned today, just unread) | no (absent/None → 0) |
| `tokens_input` / `tokens_output` | int | existing C7 accumulation | yes |
| price rates (`price_input_per_million` override or hardcoded table) | number | Settings / frontend pricing table (C18) | yes for cost |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| `tokens_cached` (per call) | int | `LLMResponse.tokens_cached` (default 0) |
| `tokens_cached` (per run) | int | `AgentState` → `query_runs.tokens_cached` → `/ask` answer payload, `GET /runs/{run_id}`, `GET /sessions/{id}` turns |
| `tokens_cached` + `last_tokens_cached` | int | `GET /stats/daily` (daily aggregate + latest completed run) |
| "X of Y from cache" line + honest cost | UI | TokenWidget (C18) + PromptBreakdown (C29) |

## External Calls
None new — reads a field Gemini's `usage_metadata` already returns on every existing call.

## Business Rules
- **Provider capture:** `GeminiProvider.complete` reads `usage_metadata.cached_content_token_count`; absent/None → `0`. The shared `LLMResponse` NamedTuple gains `tokens_cached: int = 0`; anthropic/openrouter/stub providers are untouched and default it to `0` — no behavior change. **Anthropic stays 0 this phase (deliberate):** that provider makes no cache-control calls, so `0` is honest — do NOT wire Anthropic's `cache_read_input_tokens` fields.
- **Cached tokens are a SUBSET of `tokens_input`, not additional tokens:** Gemini's `prompt_token_count` (what we record as `tokens_input`) already counts cached tokens at FULL value; `cached_content_token_count` says how many of those were served from cache. Invariant per call and per run: `0 ≤ tokens_cached ≤ tokens_input`.
- **Accumulation:** `AgentState.tokens_cached` accumulates exactly the way `tokens_input`/`tokens_output` flow today — at the two sites in `src/graph/nodes.py` where `resp.tokens_input` is consumed (`plan_action` and `force_finalize`) — and is read by `src/graph/runner.py` at persistence. **Deliberate scope bound:** the `generate_suggestions` call (`src/graph/suggestions.py`) is left OUT of cached accumulation (its `(list, in, out)` tuple return keeps its signature); this under-counts cached tokens slightly, which only makes the displayed cost slightly conservative (never understates spend).
- **Persistence:** new `query_runs.tokens_cached` column (Integer, nullable, server-default `0` so pre-Phase-14 rows read as `0`) + one new Alembic migration. Clarification short-circuit rows carry `0` like their other token fields.
- **Honest cost formula (implemented CLIENT-SIDE — ground-truth correction):** the dollar arithmetic lives in `frontend/src/components/analyse/TokenWidget.tsx` (`costUsd`), fed by the Settings prices and the hardcoded pricing table — NOT in `src/api/stats.py`/`src/api/settings.py` as the original backlog entry assumed. The backend contributes the `tokens_cached` fields; the frontend computes (all rates per-million):
  `cost_input = (tokens_input − tokens_cached) × rate_in + tokens_cached × rate_in × DISCOUNT`
  (`cost_output` unchanged). The formula is linear, so it applies identically to the "Last query" row and the "Today" aggregate (using `/stats/daily`'s aggregate `tokens_cached`). With `tokens_cached=0` it degenerates exactly to today's arithmetic. The discount applies whether the rate comes from the hardcoded table or the user-configured Settings override (the discount is model-keyed, independent of the rate source).
- **DISCOUNT constant:** a per-provider hardcoded constant, **0.25 for Gemini implicit cache**, living beside the existing hardcoded pricing table in `TokenWidget.tsx` and keyed off the model the same way the price table is. Non-Gemini models report `tokens_cached=0` this phase, so no discount entry is needed for them.
  > **Assumed (Phase-8 documented-assumption precedent):** a Settings field for the discount multiplier is deferred until a second provider actually reports cached tokens; until then a constant is the whole requirement. Resolves the backlog's "constant vs settings field" open question.
- **The C29 bars DO NOT shrink — explicit, do not "fix" later:** cached tokens still count at full value in `prompt_token_count`, so `prompt_breakdown`'s five components, its exact-sum invariant, and `total_prompt` (= cumulative `tokens_input`) are all byte-for-byte unchanged. Caching lowers COST, never the COUNT — a 24K-input query still shows 24K bars. `tokens_cached` is NOT a new key inside the `prompt_breakdown` object (the existing PromptBreakdown component renders unknown keys as component bars — adding one would corrupt the display); it reaches the widget as a separate payload-level field/prop.
- **Display rule:** the "X of Y tokens served from cache" line renders only when `tokens_cached > 0`; a cold first run or a stub run shows no line — expected, not a bug. Resumed sessions show the line from the persisted per-turn `tokens_cached`; after a reload the TokenWidget falls back to `/stats/daily`'s `last_tokens_cached` (mirroring `last_tokens_input`/`last_tokens_output`).
- **Prompt-size dependence (empirical, 2026-07-09 — the honest small-workspace story):** Gemini's implicit cache does NOT engage below a prompt-size threshold. Measured brackets on `gemini-3.1-flash-lite`: **no hits at ≤ ~3.8K tokens/call** (live user runs at ~3.3–3.8K/call and the abandoned 2.7K-token test fixture both recorded honest zeros), **~74% hit rate at ~16.5K/call** (the Step-0 spike and the shipped gate test). Google does not contractually guarantee implicit-cache hits at any size. Consequence: **a small workspace legitimately shows NO cache line at ANY iteration count, including follow-up turns** — the zeros are true (no discount is being granted) and the display is correct to stay silent. Do not treat an absent cache line on a small workspace as a defect, and do not promise the line "appears on the follow-up turn" — it appears only when the per-call prompt is large enough for Google to cache (many datasets and/or rich context notes).

## Success Criteria
- [ ] Offline: a fake Gemini response whose `usage_metadata` carries `cached_content_token_count=N` yields `LLMResponse.tokens_cached == N`; absent/None yields `0`; the other three providers return `0`.
- [ ] Offline: `AgentState.tokens_cached` accumulates across iterations at the same sites as `tokens_input` and lands on the `query_runs` row, the `/ask` answer payload, `GET /runs/{run_id}`, and `GET /sessions/{id}` turns; the migration upgrades cleanly and pre-existing rows read `tokens_cached=0`.
- [ ] Offline: `GET /stats/daily` returns the day's summed `tokens_cached` and the latest run's `last_tokens_cached`, each `0` when no completed runs exist.
- [ ] Real key (ONE scoped test — WITHIN-run caching): ONE real ask over a production-sized workspace (an engineered fixture of 10 datasets × exactly 6 columns × 20 context facts; an OFFLINE size gate asserts ≥45,000 catalog chars ≈ 16–18K prompt tokens/call before any real call) that induces `iteration_count ≥ 2` (guarded with an explicit diagnostic) records `tokens_cached > 0` with `tokens_cached ≤ tokens_input`, consistent across the persisted `query_runs` row, `GET /runs/{run_id}`, the session turn, and `GET /stats/daily`. *(Amended 2026-07-09: the original criterion — "two consecutive asks → the SECOND records cached > 0" — was BLOCKED at the Phase 14 gate as structurally unfulfillable: post-turn memory-facts extraction mutates the prompt prefix BETWEEN runs, breaking cross-run prefix identity by design, and Gemini's implicit cache does not engage below a prompt-size threshold regardless. The shipped test (`tests/integration/test_prompt_cache_real.py`) asserts within-run caching — iterations 2+ of the SAME run repeat a byte-identical prefix — which is production's actual cache pattern.)*
- [ ] Frontend: with `tokens_cached > 0`, the TokenWidget and the C29 breakdown show "X of Y from cache" and a cost strictly LOWER than the undiscounted formula would give; with `tokens_cached = 0` the cost equals today's arithmetic and no cache line renders; the C29 component bars are unchanged in both cases.
