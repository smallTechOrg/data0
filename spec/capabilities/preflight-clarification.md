# Capability: Pre-flight Clarification Check (C26)

## What It Does
Before running the agent, asks a clarifying question if the request is too ambiguous to answer well.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| question | string | `/ask` | yes |
| dataset schemas | JSON | DB | yes |
| skip_clarification | bool | `/ask` | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| clarification response | JSON | `{type:"clarification", clarification_question, run_id, session_id}` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| LLM via `LLMClient` (`<node:clarify>`) | decide proceed vs ask | on failure → proceed |

## Business Rules

- Skipped when `session_id` is present in the request (follow-up turn in an existing conversation) or `skip_clarification=true`. (Prior to Phase 6, skipping on explicit `dataset_ids` was also a condition — that field is now ignored; the session check is the real gate.)
- A clarification returns early with a thin run (status `clarification`); no agent run.
- Stub always returns "proceed".
- **Resolved/inert state (v0.5):** when a clarification turn is not the latest turn in the thread (the user has since sent another message), the card renders as an inert historical note ("✓ Resolved — you continued below.") with no action button — it cannot linger as a live prompt or re-fire the original question. Implemented via a `resolved` prop on `ClarificationTurn`; `ConversationTurnView` passes `resolved={!isLatest}`; `ConversationCard` derives `isLatest` as `i === turns.length - 1`.

## Success Criteria
- [ ] An ambiguous question returns `type:"clarification"` with a question and a `clarification` run.
- [ ] Re-submitting with `skip_clarification:true` runs the agent and returns an answer.
- [ ] A clear question proceeds directly to an answer.
