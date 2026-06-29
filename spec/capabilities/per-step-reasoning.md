# Capability: Per-step Reasoning (C33)

## What It Does
Surfaces a SHORT natural-language rationale for each ReAct step — captured inline from the same `plan_action` LLM call that already plans the step (no extra LLM calls) — and shows it next to that step's code in the Steps inspector.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| llm_response | string | `plan_action` reply (one `plan_action` LLM call per step) | yes |
| action_history | list | `/ask` response → `StepsInspector` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| reasoning (per step) | string | each `query_runs.action_history` entry → `/ask` response → `StepsInspector` |

## External Calls
None new. The reasoning is emitted by the EXISTING per-step `plan_action` call to the LLM (`LLMClient` → Gemini/stub) — no additional call, no added latency or cost.

## The reply contract (both slices implement THIS, exactly)

Each non-final `plan_action` reply is, in order:

1. An OPTIONAL single leading line beginning with the literal marker `REASONING:` (case-insensitive), e.g.
   `REASONING: First inspect the columns so I know the exact price field name.`
2. Then the bare pandas expression to run next — EXACTLY as today: no prose, no backticks, no fences.

The `FINAL ANSWER:` path is unchanged — a `FINAL ANSWER:` reply carries no `REASONING:` line and is parsed exactly as today.

**Parsing rule (the node):** if the reply's FIRST non-empty line starts with `REASONING:` (case-insensitive, optional leading whitespace), that line's text after the marker is the step's `reasoning` (trimmed); the REMAINDER of the reply (everything after that first line) is then passed UNCHANGED to the existing `_extract_code` (for an action) / `_strip_final_answer` (for a final answer). If there is NO leading `REASONING:` line, `reasoning` is the empty string `""` and the ENTIRE reply flows through the existing extraction unchanged — i.e. a bare-expression reply (today's behaviour, and the stub's `df.describe().to_string()`) parses to empty reasoning + the identical code.

This makes the rationale strictly additive: the bare pandas expression `_extract_code` returns is byte-for-byte what it returns today, and a reply with the reasoning segment absent never breaks execution (graceful fallback to `""`).

## Surfaces / files
- `src/prompts/plan_action.md` — instruct the model to PREFIX each action reply with one `REASONING: <one short sentence>` line, then the bare expression on the next line(s); `FINAL ANSWER:` replies carry no `REASONING:` line. (slice-A)
- `src/graph/nodes.py` — in `execute_action`, split the optional leading `REASONING:` line off `llm_response` BEFORE `_extract_code` runs; store `reasoning` (default `""`) on the appended `action_history` step dict; `_extract_code` keeps returning today's bare expression. Parsing stays in `nodes.py` (no change to `src/graph/sandbox.py`). (slice-A)
- `frontend/src/lib/api.ts` — add `reasoning?: string` to the `AskStep` type only. (slice-B)
- `frontend/src/components/analyse/StepsInspector.tsx` — render `step.reasoning` next to each step's code when present; render NOTHING when absent/empty (no layout break). (slice-B)

## Business Rules
- **No extra LLM call.** Reasoning is captured from the SAME single `plan_action` call per step — never a post-hoc explanation pass.
- **No DB migration.** `query_runs.action_history` is an existing JSON column; each entry GAINS a `reasoning: str` field. Entries written before this capability (or replies with no `REASONING:` line) read back as `""`.
- **State unchanged.** Per-step reasoning lives inside `action_history` entries; NO new top-level `AgentState` field is added (entries already carry per-step `action`/`result`/`is_error`).
- **Execution path preserved.** After the optional `REASONING:` line is removed, the remaining bare expression executes EXACTLY as today — same `action` recorded, same `result`. A reply missing the `REASONING:` line still executes its code.
- **Stub / offline suite stays green.** The stub's `_plan` first-action output `df.describe().to_string()` has no `REASONING:` line, so it parses to `reasoning=""` + the unchanged expression — the stub needs no change and the existing stub-based unit tests keep passing (real-Gemini replies are where non-empty reasoning appears).
- **Frontend graceful absence.** Empty/absent `reasoning` renders nothing; the inspector layout for reasoning-less steps is identical to today.

## Success Criteria
- [ ] (unit/stub) A `plan_action` reply of the form `REASONING: <text>\n<expr>` parses to `reasoning="<text>"` on the step AND `action`/`result` identical to running `<expr>` alone (execution unchanged).
- [ ] (unit/stub) A bare-expression reply (no `REASONING:` line) parses to `reasoning=""` and the unchanged `action`/`result`; the offline `tests/unit/` suite stays fully green (no new failures vs the 213-passing baseline).
- [ ] (integration, real Gemini) A real `/ask` run records non-empty `reasoning` on at least one `action_history` step.
- [ ] (frontend) When a step has non-empty `reasoning`, the Steps inspector shows a short rationale line next to that step's code; when absent/empty it renders nothing and the layout is unchanged.

## Out of Scope (non-goals)
- No upfront planning stage / overall plan synthesis.
- No plan-steering or user editing of the plan.
- No step check-off / todo tracking / progress checklist.
- ONLY per-step reasoning capture + display.
