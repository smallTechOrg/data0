# Capability: Per-run Token Tracking (C7)

## What It Does
Accumulates input/output token counts across every LLM call in a run and persists them.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| LLM responses | provider usage | each LLM call | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| tokens_input, tokens_output | int | `query_runs` row + `/ask` response |
| tokens_cached | int | `query_runs` row + `/ask` response (C39 — same accumulation path, see below) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| LLM provider | report usage | if unavailable, estimate or 0; never crash |

## Business Rules
- Token counts accumulate across `plan_action`, `force_finalize`, and graph-adjacent calls (clarify/suggest) for the same run.
- **`tokens_cached` (C39, Phase 14):** accumulates alongside `tokens_input` at `plan_action` + `force_finalize` ONLY — the `generate_suggestions` call is deliberately excluded (documented scope bound: the under-count only makes the displayed cost slightly conservative). A subset of `tokens_input` (`0 ≤ tokens_cached ≤ tokens_input`), reported only by the Gemini provider this phase; stub/anthropic/openrouter report `0` (honest — no cache-control calls). Persisted on `query_runs.tokens_cached` (nullable, default 0). Full rules in [prompt-cache-accounting.md](prompt-cache-accounting.md).
- Stub mode reports plausible/zero counts without error.

## Success Criteria
- [ ] After a multi-iteration run against real Gemini, `tokens_input` and `tokens_output` are > 0 and persisted.
- [ ] The `/ask` response carries the same totals as the `query_runs` row.
