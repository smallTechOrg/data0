# Capability: Suggested Questions — session starters + clarification candidates (C37)

## What It Does
Puts tap-able question chips in front of the user at the two moments the composer is empty-handed: **(1)** "Try asking:" starter chips when the Analyse tab's conversation is empty and the workspace has at least one dataset, and **(2)** up to 3 refined candidate questions on a C26 clarification turn, so the user can tap a sharper version of their question instead of typing an answer. Both reuse the existing suggestion-chips UI and its click-fills-the-composer behavior, unchanged.

> **Why a NEW file (not an extension):** no existing capability file owns follow-up suggestions — `generate_suggestions` was delivered inside Phase 3's session work and is documented only in `spec/agent.md` ("Graph-adjacent single LLM calls") and `spec/api.md` (the `/ask` payload). C26's file ([preflight-clarification.md](preflight-clarification.md)) owns only the clarification *gate*, not suggestions. C37 therefore gets its own file; the pre-existing post-answer follow-up chips remain documented where they are (referenced here, not restated).

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset catalog (metadata only) | filenames + `columns_json` + compressed `context_facts` notes | DB (`datasets` rows — NO frames loaded, no file reads) | yes (starters) |
| question | string | `/ask` (the C26 pre-flight input, unchanged) | yes (clarification candidates) |
| dataset schemas | text block | `_candidate_schemas_text` (the C26 pre-flight input, unchanged) | yes (clarification candidates) |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| starter questions | `{questions: string[]}` (0–3 items) | `GET /suggestions/starters` response (contract in `spec/api.md`) |
| refined candidate questions | `suggested_questions: string[]` (0–3 items) | the `type:"clarification"` payload of `POST /ask` (contract in `spec/api.md`) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| LLM via `LLMClient.call_model` (tag `<node:suggest>`) | ONE call: generate ≤3 starter questions from the metadata-only catalog | return `[]` → endpoint responds 200 `{questions: []}`; never a 5xx, never raises |
| LLM via `LLMClient.call_model` (tag `<node:clarify>`) | the SAME single C26 pre-flight call, extended — no extra roundtrip; the reply now carries the clarifying question AND ≤3 refined candidates | fail-open to proceed (unchanged); an unparseable extended reply falls back to today's behavior (whole reply = the clarification question, candidates `[]`) |

## Business Rules

### Session-start starters
- **Trigger:** the Analyse conversation shows ZERO turns. The frontend fetches `GET /suggestions/starters` once for that empty-conversation view; while loading and whenever `questions` is empty, the "Try asking:" block is simply hidden (no spinner, no dangling label — same discipline as `SuggestionChips`).
- **No session required.** The endpoint takes no session (and no body/params) — chips seed the composer BEFORE any session exists, exactly matching today's chip-click behavior (fill the composer; the session is created by the eventual `POST /ask`).
- **Metadata only, mirroring `setup`'s catalog.** The catalog text is built from `datasets.columns_json` plus the compressed `context_facts` rendered facts-first (same convention as `setup`'s `_facts_as_notes` — raw notes are never sent; a dataset with no cached facts shows columns only). **NO DataFrames are loaded and no data files are read** — this endpoint must stay cheap enough to hit on every empty-tab view.
- **One LLM call, module reuse.** `generate_starter_questions(catalog_text)` lives in `src/graph/suggestions.py`, reusing its `_coerce_string_list` JSON-array parsing, the ≤3 cap (`_MAX_SUGGESTIONS`), and the prompt-loading helper, with a NEW prompt `src/prompts/starters.md`. It injects the EXISTING `<node:suggest>` tag — the reply grammar (a bare JSON array of ≤3 question strings) is identical to the follow-up-suggestions contract, so the stub provider needs ZERO changes and deterministically returns `[]` (the UI hides the block — offline/stub showing no starters is correct, not a bug).
- **Never fails.** Empty workspace → 200 `{questions: []}` (short-circuits BEFORE any LLM call). LLM error / parse failure / stub → 200 `{questions: []}`. The endpoint never returns a 5xx — mirroring `generate_suggestions`' never-fails posture.
- **NOT Fast-Mode-gated.** Starters happen before any query exists, so `fast_mode` (a per-`/ask` flag) cannot apply to them by construction.
- **Token accounting:** the starters call belongs to NO run, so its tokens are not attributed to `query_runs` or `GET /stats/daily` (which aggregate per-run usage). Accepted, documented gap — one small call per empty-tab view.
- > **Assumed:** the frontend memoizes the fetched starters for the lifetime of the Analyse-tab mount — a "New session" reset reuses them rather than re-calling the LLM (the dataset catalog rarely changes mid-visit; a page reload refetches). Chosen to keep one LLM call per visit instead of one per reset.

### Clarification-turn candidates
- **Same single LLM call — the pre-flight path stays fast.** `check_clarification` (`src/graph/preflight.py`, C26) makes its ONE call exactly as today; only the requested reply shape and the parsing change. No second roundtrip is ever added.
- **Reply contract (the prompt's requested grammar, `src/prompts/clarify.md`):**
  - Answerable as-is → reply **exactly `proceed`** (unchanged — this also keeps the stub provider's `<node:clarify>` → `"proceed"` branch and its existing tests passing verbatim, with zero stub changes).
  - Genuinely ambiguous → reply with ONE JSON object:
    ```json
    {"question": "<ONE short clarifying question>",
     "suggestions": ["<refined candidate 1>", "<refined candidate 2>", "<refined candidate 3>"]}
    ```
    with 0–3 `suggestions`, each a complete, self-contained refined version of the user's question that could be submitted as-is. (JSON-object-with-span-extraction chosen to match how this repo already parses structured replies robustly — `compress.md`/`suggest.md`'s JSON with `[...]`-span fallback in `_coerce_string_list`.)
- **Parsing (graceful, ordered — in `check_clarification`):**
  1. LLM error / empty reply → `None` (proceed) — fail-open, unchanged.
  2. Normalized reply starts with / contains `proceed` in its first 16 chars → `None` — unchanged.
  3. Strip an optional code fence, extract the FIRST `{...}` span (`re.search(r"\{.*\}", text, re.DOTALL)`), `json.loads` it; if it is a dict with a non-empty string `question` → that is the clarifying question, and `suggestions` is coerced to ≤3 non-empty strings (missing/invalid `suggestions` → `[]`).
  4. ANY parse failure (no span, bad JSON, missing/empty `question`) → the WHOLE trimmed reply (stripped of wrapping backticks/quotes exactly as today) is the clarification question, with candidates `[]` — i.e. a model that ignores the JSON instruction degrades to today's exact behavior. Parsing never blocks or downgrades the clarification itself.
- **Return type:** `check_clarification` returns `None` (proceed) or a `ClarificationResult` NamedTuple `(question: str, suggestions: list[str])` — NamedTuple per the repo's `LLMResponse` convention. The runner (`src/graph/runner.py`) threads it into the clarification payload: `clarification_question` = `.question`, **`suggested_questions`** = `.suggestions` (possibly `[]`).
- **Live-only, no persistence.** No DB column is added — exactly like post-answer follow-up suggestions today (`_turn_payload` already defensively returns `[]` for `suggested_questions`), a resumed/reloaded clarification turn shows no chips. Parity, not an omission.
- **Fast Mode:** already skips the pre-flight ENTIRELY (C35), so clarification candidates are naturally absent under Fast Mode — no new rule exists or is needed.
- **Resolved clarifications show no chips.** Chips render only under the LATEST (live) clarification turn; once the user continues, the turn becomes the inert "✓ Resolved" note (C26's resolved-state rule) with no chips — a stale candidate can never re-fire.

### Shared UI behavior
- Both surfaces reuse the existing chips component (`frontend/src/components/analyse/SuggestionChips.tsx`, rendered from `ConversationCard.tsx`), which gains an optional `label` prop (default: today's "Follow-up suggestions"; starters use "Try asking:"; clarification candidates use a refine-oriented label). Clicking a chip fills the composer — the existing `pickSuggestion` behavior, unchanged; it never auto-submits.

## Surfaces / files
- `src/graph/preflight.py` — `ClarificationResult` NamedTuple; extended reply parsing with the ordered fallback above. (backend slice)
- `src/prompts/clarify.md` — updated reply grammar (`proceed` OR the JSON object); the bias-to-proceed rule is unchanged. (backend slice)
- `src/graph/suggestions.py` — ADD `generate_starter_questions(catalog_text) -> list[str]` reusing the module's parsing/cap/prompt helpers; `generate_suggestions` itself is unchanged. (backend slice)
- `src/prompts/starters.md` (NEW) — the starter-generation prompt (reply: a bare JSON array of ≤3 question strings). (backend slice)
- `src/graph/runner.py` — the clarification short-circuit payload gains `suggested_questions`. (backend slice)
- `src/api/suggestions.py` (NEW) — `GET /suggestions/starters`, registered in `create_app()`; builds the metadata-only catalog, short-circuits on an empty workspace, never 5xx. (backend slice)
- `src/llm/providers/stub.py` — NOT edited: `<node:clarify>` → `"proceed"` and `<node:suggest>` → `"[]"` already cover both new call sites. (contract note, no change)
- `frontend/src/lib/api.ts` — `api.suggestions.starters()` for the new endpoint (namespaced like `api.connections.*`); document `suggested_questions` on the clarification variant of `AskResponse` (the optional field already exists on the type). (frontend slice)
- `frontend/src/components/analyse/SuggestionChips.tsx` — optional `label` prop. (frontend slice)
- `frontend/src/components/analyse/ConversationCard.tsx` — the empty-state "Try asking:" block (fetch-once + hide-when-empty) and chips under the latest clarification turn; clarification turns carry their candidates into the `Turn` model. (frontend slice)
- `frontend/src/components/analyse/ConversationTurnView.tsx` — the `Turn` type gains the clarification candidates field threaded to the live clarification card. (frontend slice)
- `tests/unit/test_suggested_questions_stub.py` (NEW) — offline coverage, see Success Criteria. (backend slice)
- `tests/integration/test_suggested_questions_real.py` (NEW) — real-Gemini coverage, **deferred-verification** (see below). (backend slice)

## Phase
Phase 10 (see `spec/roadmap.md` → "### Phase 10 — Suggested questions at session start and on clarification turns").

## Success Criteria

### Offline (stub / unit — the authoritative gate TODAY)
> The real-key gate is temporarily blocked by the Gemini free-tier **500-requests/day quota being exhausted** (see `spec/roadmap.md` → Backlog → "Real-key test-suite pacing"). These offline criteria alone gate the Phase 10 build; the real-key criteria below are deferred-verification, to be run after the daily reset (or on a properly billed key).

- [ ] (unit/stub) `GET /suggestions/starters` with ≥1 dataset present returns **200** `{questions: []}` under the stub provider (the `<node:suggest>` tag branch), envelope `ok(...)`.
- [ ] (unit/stub) `GET /suggestions/starters` on an EMPTY workspace returns **200** `{questions: []}` WITHOUT making any LLM call (asserted via a spy).
- [ ] (unit) `GET /suggestions/starters` with `LLMClient` raising returns **200** `{questions: []}` — never a 5xx.
- [ ] (unit) `generate_starter_questions` builds its catalog from `columns_json` + `context_facts` only — no frame/file read (asserted via a spy on the loaders / no `uploads/` access).
- [ ] (unit) Extended clarify parsing: a mocked reply `{"question": "...", "suggestions": ["a","b","c"]}` (bare AND fenced) → `ClarificationResult` with that question and 3 candidates; >3 suggestions are capped at 3; missing/invalid `suggestions` → `[]`.
- [ ] (unit) A mocked plain-text reply (no JSON) → `ClarificationResult(whole reply, [])` — today's behavior preserved as the fallback.
- [ ] (unit) `"proceed"` → `None`, and an LLM error → `None` (fail-open) — the EXISTING `tests/unit/test_preflight_stub.py::test_check_clarification_stub_proceeds` / `test_check_clarification_fails_open` keep passing unmodified.
- [ ] (unit/stub) `POST /ask` driven to a clarification (mocked extended reply) returns `type:"clarification"` with `suggested_questions` populated; a fallback-parsed clarification returns `suggested_questions: []` — the clarification itself is never blocked by a parse failure.
- [ ] (unit/stub) `run_agent(fast_mode=True, ...)` still never calls `check_clarification` (existing C35 test keeps passing) — clarification candidates are structurally absent under Fast Mode.
- [ ] (frontend) With an empty conversation and a non-empty starters response, the "Try asking:" block renders; clicking a chip fills the composer and does NOT auto-submit; an empty response renders nothing. Chips under a clarification turn render only while it is the LATEST turn.

### Real-key (integration, real Gemini — DEFERRED VERIFICATION until the daily quota resets)
- [ ] (integration, real Gemini) `GET /suggestions/starters` with real datasets uploaded returns 1–3 non-empty questions that reference actual dataset content (column names / topics from the catalog).
- [ ] (integration, real Gemini) An ambiguous first-turn question returns `type:"clarification"` with a clarifying question AND 1–3 refined candidates, produced by the SAME single pre-flight call (assert exactly one `<node:clarify>` LLM call via a counting wrapper — no extra roundtrip).
- [ ] (integration, real Gemini) Submitting one of the returned refined candidates as the next `/ask` proceeds to a real `type:"answer"` (the candidates are genuinely runnable questions).

## Out of Scope (non-goals)
- No persistence of starter or clarification suggestions (no DB column; reload/resume shows no chips — parity with today's follow-up chips).
- No auto-submit on chip click — chips only fill the composer, everywhere.
- No change to `generate_suggestions` (post-answer follow-ups) or its Fast-Mode skip (C35).
- No per-dataset or per-session starter scoping — starters are workspace-wide, from the whole catalog.
- No streaming/regenerate affordance for chips.
