# Capability: Fast Mode — a single latency toggle (C35)

## What It Does
A single per-query, user-facing toggle in the Analyse composer that trades a little answer depth for speed by sending the LLM *less work per request*. It targets the two things that dominate loop latency — the number of LLM roundtrips and the size of the fastest-growing prompt bucket (`action_history`) — while deliberately leaving model/provider choice to the user's Settings (Fast Mode never switches model/provider). Default OFF; opt in per question.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| fast_mode | bool | `/ask` request body | no (default `false`) |
| question | string | `/ask` | yes |
| max_iterations (settings/DB override) | int | `config.settings` / `SettingRow` | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| fast_mode (echoed) | bool | `/ask` response, so the UI can label a Fast Mode turn |
| tightened iteration cap | int | `AgentState.max_iterations` for this request only (not persisted to settings/DB) |

## External Calls
None new. Fast Mode changes HOW EXISTING calls are shaped/skipped; it introduces no new LLM or HTTP call.

| System | Operation | Fast-Mode effect |
|--------|-----------|-------------------|
| LLM via `LLMClient` (`plan_action`) | per-iteration ReAct call | unchanged call, but fewer iterations run (tighter cap) and a shorter transcript is sent (truncated `action_history`) plus a brevity instruction |
| LLM via `LLMClient` (`<node:clarify>`) | pre-flight clarification | SKIPPED entirely — `run_agent` never invokes `check_clarification` when `fast_mode=true` |
| LLM via `LLMClient` (`<node:suggest>`) | post-answer follow-ups | SKIPPED entirely — `run_agent` never invokes `generate_suggestions` when `fast_mode=true` |

## Business Rules

- **Tightened `max_iterations` (request-scoped only).** When `fast_mode=true`, the effective cap for THIS request is `5` (see "Resolved decisions" below), overriding both `settings.max_iterations` and any DB `SettingRow` override — Fast Mode wins over the settings-configured value for that one request. It is never written back to `settings`/DB; the next non-Fast-Mode request reverts to the normal cap. `AgentState.max_iterations` and the `recursion_limit` derived from it in `run_agent` both use the tightened value.
- **Skips pre-flight clarification (C26).** `run_agent` does not call `check_clarification` when `fast_mode=true`, regardless of `run_clarification`/first-turn status — the run always proceeds on the model's best guess. This is a strict skip (not a shorter clarification call): zero clarification roundtrips in Fast Mode.
- **Skips follow-up suggestions.** `run_agent` does not call `generate_suggestions` when `fast_mode=true`; `suggested_questions` is `[]` on the response, same shape as any other empty-suggestions run — the frontend requires no special-casing.
- **Truncates each action result before it re-enters `action_history`.** In Fast Mode, immediately before a step dict is appended in `execute_action`, its `result` string is truncated to `500` characters (with a short `"… [truncated]"` marker appended when truncation occurred). This applies to the STORED/re-transmitted `action_history` entry only — the truncation happens once, at append time, so it compounds correctly across iterations (each later prompt re-sends the already-shortened result, not the original). It does not affect `is_error` detection (truncation happens after the error/non-error result string is chosen) and does not affect what is returned to the DB/UI for that step's `result` field — the UI shows the same (truncated) string the model saw, so there is no "the model saw less than what I see" mismatch.
- **Brevity instruction, not a token cap.** In Fast Mode, the `plan_action` system prompt gains ONE additional instruction line asking for a shorter final answer (target: a few sentences unless the question needs a table/list). This is prompt-level guidance only — `LLMClient.complete` is NOT called with a `max_output_tokens`/`max_tokens` override in Fast Mode. Explicitly rejected: a hard output-token cap (risks mid-sentence truncation).
- **Disables the forced-chart retry.** In Fast Mode, `after_plan`'s chart guardrail (loop back to `plan_action` once more when the user asked for a chart but none was produced yet, capped today at `chart_force_count < 2`) never fires — a `FINAL ANSWER:` with `wants_chart=true` and no chart finalizes immediately in Fast Mode instead of forcing one extra iteration. Charts are NOT disabled outright: if the model happens to call `echart(...)` on its own within the tightened iteration budget, the chart still renders. This is strictly a removal of the FORCED extra iteration, not a removal of charting.
- **Model/provider untouched.** Fast Mode never reads or writes `llm_model` / provider selection; `LLMClient`'s provider/model resolution is completely unaffected. A Fast Mode request and a non-Fast-Mode request on the same session use the identical model.
- **Reasoning effort untouched.** No change to per-step reasoning (C33) capture, thinking/reasoning-effort parameters, or any other prompt content beyond the brevity line and the tightened cap.
- **Per-query, not global.** `fast_mode` is a request-body flag on `/ask`, not a `settings`/`SettingRow` value — it does not persist across turns or sessions. Each `/ask` call states its own `fast_mode`; a session can freely mix Fast Mode and normal turns.
- **Clarification skip does not imply session-start skip.** Fast Mode's clarification skip is evaluated independently of (and in addition to) the existing "skip on follow-up turn" rule (C26) — either condition alone is enough to skip.

## Resolved Decisions (open questions from the backlog entry — no interactive intake for a capability-add; documented assumptions per the project's established pattern, e.g. the C28 numbering-gap note)

- **Per-query override vs. global default → per-query toggle in the Analyse composer, default OFF.** Chosen because Settings already deliberately owns model/provider (the backlog entry insists the two stay decoupled), and a visible per-query switch next to the question keeps the trade-off low-friction and legible turn-by-turn rather than a silent standing state the user forgets is on. A future global default is not precluded by this shape (the request flag can be pre-filled from a remembered UI preference later) but is out of scope here.
- **Tightened `max_iterations` value → `5`.** Roughly half the default `12`, and one below the `6` implicit in the graph's own fallback default (`state.get("max_iterations", 6)` in `nodes.py`/`edges.py`) so Fast Mode is measurably tighter than even an unconfigured normal run, while still leaving room for a `setup` + a couple of `execute_action` iterations + `finalize` on most questions.
- **Token-delta display in the C29 prompt-breakdown widget → SKIPPED in this pass.** The C29 widget (`spec/capabilities/context-window-display.md`) already reports `total_prompt`/`tokens_output` per run, so a user CAN already visually compare a Fast Mode run's numbers against a prior normal run on the same session without any new UI — that is enough signal for this phase. Adding an explicit "vs normal mode" delta comparison would require persisting or estimating a counterfactual non-Fast-Mode token count, which is speculative work beyond what this capability promises. Biasing away from scope creep per the task brief.

## Surfaces / files
- `src/graph/runner.py` — `run_agent` gains a `fast_mode: bool = False` parameter; applies the tightened cap (overriding the settings/DB value), skips the `check_clarification` call, and skips the `generate_suggestions` call when `fast_mode=True`. (backend slice)
- `src/graph/nodes.py` — `execute_action` truncates a step's `result` to 500 chars before appending to `action_history` when running in Fast Mode; `plan_action`'s system-prompt assembly includes the brevity line when Fast Mode is active. `AgentState` carries the active `fast_mode` flag so downstream nodes can read it without threading a new parameter through every call. (backend slice)
- `src/graph/edges.py` — `after_plan`'s chart-guardrail branch is skipped when `state.get("fast_mode")` is true. (backend slice)
- `src/graph/state.py` — `AgentState` gains a `fast_mode: bool` field (request-scoped, not persisted). (backend slice)
- `src/prompts/plan_action.md` — the brevity instruction line, included conditionally (see nodes.py). (backend slice)
- `src/domain/ask.py` — `AskRequest` gains `fast_mode: bool = False`. (backend slice)
- `src/api/ask.py` — threads `req.fast_mode` into `run_agent(...)`; echoes `fast_mode` on the response payload. (backend slice)
- `frontend/src/lib/api.ts` — `AskArgs` gains `fastMode?: boolean`; `api.ask` sends `fast_mode` in the body; `AskResponse`/`TurnView` gain `fast_mode?: boolean`. (frontend slice)
- `frontend/src/components/analyse/ConversationCard.tsx` (or a small new `FastModeToggle` sub-component rendered next to the composer) — the visible toggle, default OFF, threaded into `runAsk`/`api.ask`. (frontend slice)

## Phase
Phase 8 (see `spec/roadmap.md` → "### Phase 8 — Fast Mode").

## Success Criteria
- [ ] (unit/stub) A stub-provider run with `fast_mode=true` uses `max_iterations=5` regardless of the configured `settings.max_iterations`/DB override; a `fast_mode=false` (or omitted) run is unaffected and still honors the configured cap.
- [ ] (unit/stub) `run_agent(fast_mode=True, run_clarification=True, ...)` never calls `check_clarification` (asserted via a mock/spy), even on a first turn where a normal run would.
- [ ] (unit/stub) `run_agent(fast_mode=True, ...)` never calls `generate_suggestions`; the response's `suggested_questions` is `[]`.
- [ ] (unit/stub) An `execute_action` step whose raw result exceeds 500 chars is stored (and re-sent in the next iteration's prompt) truncated to ≤500 chars (+ marker) when `fast_mode=True`; an identical step under `fast_mode=False` stores the untruncated result.
- [ ] (unit/stub) `after_plan`'s forced-chart retry never fires when `fast_mode=True` even when `wants_chart=True` and no chart was produced — a `FINAL ANSWER:` finalizes immediately instead of looping back to `plan_action`.
- [ ] (integration, real Gemini) On the SAME question (one that in normal mode would trigger a clarification and/or several ReAct iterations), a Fast Mode run completes in **strictly fewer LLM roundtrips** (iteration_count + clarification-call + suggestion-call, summed) than an equivalent non-Fast-Mode run in the same session/dataset context — asserting a real, measurable behavior difference, not just that the flag threads through unchanged.
- [ ] (integration, real Gemini) A Fast Mode run's `iteration_count` never exceeds `5`.
- [ ] (integration, real Gemini) A Fast Mode run on a question a normal run would ask a clarifying question for instead proceeds directly to an answer (`type:"answer"`, never `type:"clarification"`).
- [ ] (integration, real Gemini) Model/provider is identical between a Fast Mode and non-Fast-Mode run in the same settings configuration (asserted via the response/`GET /health` model id, or via a captured `LLMClient` call — no model-switching side effect).
- [ ] (frontend) The Analyse composer shows a Fast Mode toggle, default OFF; enabling it and asking a question sends `fast_mode:true` in the `/ask` body; the toggle state does not persist to Settings and resets are per-composer-session only (no cross-reload persistence requirement).

## Out of Scope (non-goals)
- No model/provider switching — Settings' model/provider choice is completely unaffected by Fast Mode.
- No hard `max_output_tokens`/`max_tokens` cap — brevity is prompt-level guidance only.
- No change to reasoning/thinking effort parameters.
- No global Fast Mode default in Settings — per-query only in this phase.
- No token-delta ("Fast Mode saved you N tokens") display in the C29 widget in this phase.
- Charts are not disabled in Fast Mode — only the FORCED extra retry iteration is removed.
