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
- `prompt_breakdown` describes the **composition of the most recent assembled `plan_action` prompt** (the last, largest ReAct iteration) — NOT the cumulative cost of the whole run.
- Components: `system_overhead`, `dataset_schemas`, `history`, `memory`, `dataset_notes`, `action_history`, `total_prompt`. The six non-total components **partition** that one prompt with no overlap and no omission, so `total_prompt` == their **exact** sum. All are `chars/4` estimates.
- `system_overhead` includes the `plan_action.md` **system template** plus the fixed scaffolding (the plan tag, the `## Question` section incl. the question text, the wrap-up block when present, and the instruction footer) — so it is the largest fixed bucket.
- `dataset_schemas` measures the whole `## Datasets` section; dataset notes are folded into the schema block by `setup`, so `dataset_notes` is `0` (counting it separately would double-count). `memory`, `history`, and `action_history` measure the `## Persistent memory`, `## Earlier in this conversation`, and `## Actions so far` sections respectively (each `0` when absent).
- The **cumulative per-query token cost** (summed real provider input/output tokens across all iterations) is reported SEPARATELY via `tokens_input` / `tokens_output` (the Token usage panel), NOT inside `prompt_breakdown`.
- At-rest bar estimates context fill before a run from datasets + memory.

## Success Criteria
- [ ] After a run, `prompt_breakdown` includes all named components and `total_prompt` == their exact sum.
- [ ] The sidebar budget bar renders a non-zero estimate when datasets/memory exist.
