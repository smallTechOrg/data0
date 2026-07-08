# Capability: Live Context-window Display (C29)

## What It Does
Shows a token-budget estimate at rest and a per-component prompt breakdown after each run.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| datasets/memory/history sizes | derived | DB | yes |
| prompt_breakdown | JSON | `/ask` response | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| sidebar budget bar + breakdown | UI | Analyse sidebar / turn |

## External Calls
None.

## Business Rules
- `prompt_breakdown` represents the **CUMULATIVE input of the whole query** — the real provider-reported input tokens summed across all ReAct iterations — so it aligns with the "Last query (In / Out)" row. `total_prompt` == the run's real cumulative `tokens_input`.
- Components: `system_overhead`, `dataset_schemas`, `history`, `memory`, `action_history`, `total_prompt`, and `tokens_output`. The five non-total/non-output components are derived by accumulating each bucket's **char counts** across all iterations, then **scaling** those cumulative char counts to the real cumulative `tokens_input` (`round(bucket_chars / total_chars * tokens_input)`). The rounding residual is absorbed into the largest bucket so the five sum **EXACTLY** to `total_prompt`.
- `tokens_output` carries the run's real **cumulative output** tokens for the response.
- `system_overhead` covers the `plan_action.md` **system template** plus the fixed scaffolding (the plan tag, the `## Question` section incl. the question text, the wrap-up block when present, and the instruction footer). After scaling it may no longer be the largest bucket.
- `dataset_schemas` measures the whole `## Datasets` section; dataset notes are folded into the schema block by `setup` and are never counted separately (there is no `dataset_notes` bucket — counting them again would double-count). `memory`, `history`, and `action_history` measure the `## Persistent memory`, `## Earlier in this conversation`, and `## Actions so far` sections respectively (each `0` when absent).
- Fallback (a run that never planned — clarification short-circuit, cancelled-before-plan, or zero total chars): the five buckets are `0`, `total_prompt` is the (likely `0`) `tokens_input`, and `tokens_output` is the cumulative output. Never crashes.
- At-rest bar estimates context fill before a run from datasets + memory.
- **Cached-tokens line (C39, Phase 14):** when the run's payload-level `tokens_cached > 0`, the breakdown shows an informational **"X of Y tokens served from cache"** line (X = `tokens_cached`, Y = `total_prompt`). `tokens_cached` arrives as a separate prop from the run/turn payload — it is **NOT a key inside the `prompt_breakdown` object** (the component renders unknown keys as component bars, which would corrupt the display). No line renders when `tokens_cached = 0` (cold/stub run — expected).
- **The bars DO NOT shrink — explicit rule, do not "fix" later:** cached tokens are counted at FULL value inside `prompt_token_count`/`tokens_input`, so `total_prompt`, the five components, and the exact-sum invariant are byte-for-byte unchanged by caching. Caching lowers COST (see [token-usage-widget.md](token-usage-widget.md) / [prompt-cache-accounting.md](prompt-cache-accounting.md)), never the COUNT. A 24K-input query still shows 24K bars.

## Success Criteria
- [ ] After a run, `prompt_breakdown` includes all named components, `total_prompt` == their exact sum, `total_prompt` == the run's cumulative `tokens_input`, and `tokens_output` == the run's cumulative output.
- [ ] The sidebar budget bar renders a non-zero estimate when datasets/memory exist.
- [ ] With `tokens_cached > 0` the breakdown shows the "X of Y from cache" line while every component bar and `total_prompt` are identical to what an uncached run of the same token counts would show; with `tokens_cached = 0` no cache line renders.
