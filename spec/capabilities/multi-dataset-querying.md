# Capability: Multi-dataset Querying (C14)

## What It Does
Lets a single question reason across multiple datasets loaded together.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset catalog | list | ALL workspace datasets (agent picks + lazily loads) | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| answer over multiple frames | string | `/ask` response |

## External Calls
None beyond the ReAct loop.

## Business Rules
- `setup` builds a metadata-only catalog of ALL datasets; the sandbox exposes them as `df1`/`df2`/… plus `<filename_stem>` aliases (`df` is the first), each **lazily loaded** the first time the agent references it.
- Selection is agent-driven (C19): the agent picks which catalog datasets to load — nothing is client-scoped.

## Success Criteria
- [ ] A question that joins/compares two datasets returns a correct answer referencing both (real Gemini).
- [ ] `df1` and `df2` (and stem aliases) are available in the sandbox.
