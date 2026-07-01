# Capability: Multi-provider LLM (C21)

## What It Does
Routes every LLM call through one `LLMClient` over Gemini, OpenRouter, or a node-tag-branching stub, auto-selected by which key is set.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| prompt (+ injected node tag) | string | nodes/helpers | yes |
| provider config | settings | `.env` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| completion | string | caller |
| resolved provider | string | `/health` (drives stub banner) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini / OpenRouter | `call_model` | surfaced as recoverable/fatal per node |
| stub | canned per node tag | never fails |

## Business Rules
- `AGENT_LLM_PROVIDER` ∈ `auto|gemini|openrouter|stub`; blank → auto-detect (gemini key → gemini; else openrouter key → openrouter; else stub). Existing `anthropic` retained.
- Stub branches ONLY on injected node tags (`<node:plan>`/`<node:finalize>`/`<node:clarify>`/…), never on prose. Tag→output table in `spec/agent.md`.
- No node calls a provider SDK directly — always via `LLMClient`.

## Success Criteria
- [ ] With `AGENT_GEMINI_API_KEY` set, `/health` reports `provider:"gemini"` and real answers are produced.
- [ ] With no key set, `/health` reports `provider:"stub"`, the yellow banner shows, and stub answers branch correctly by node tag.
- [ ] Setting `AGENT_LLM_PROVIDER=openrouter` with its key routes to OpenRouter.
