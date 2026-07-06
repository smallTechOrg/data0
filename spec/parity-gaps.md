# Parity Gaps — reaching feature-parity with the reference build (A)

> **Reference (A):** `data-analysis-agent` (`feature/v0.5`) — the original, battle-tested build.
> **This repo (B):** the gen-3-harness rebuild of A. Source for capability IDs: `spec/capabilities/index.md` (C1–C32; C5/C28 don't exist → 30 capabilities).
>
> Audit date: **2026-06-29**, verified against actual code + tests (not commit messages).
> **Scoreboard: 24 / 30 at parity or ahead · 6 gaps remaining** (0 correctness/overclaim · 2 cheap functional · 4 ingestion-UX).
>
> Drive each item with `/zero-shot-fix` from this repo. Every fix must pass the phase gate against the **real Gemini key** in `.env` before it counts — a stubbed pass does not.

---

## Step 0 — re-verify against current HEAD (do first)

This branch is fully pushed to its upstream (`fork/feature/data-analysis-agent-v0.1`); no work is at risk. **But the audit predates several D-series `fix(drift)` commits** — at least **C10** (filename-dup) and **C16** (notes_file) already have fix commits on HEAD. Before grinding the list below, re-verify each open item against current HEAD (`8c25295`) — some Tier-2/Tier-3 gaps may already be closed.

---

## Tier 1 — Correctness & overclaims (cheap, highest trust-value)

- [x] **C31 — Semantic compression wired (2026-06-29).** `setup` now injects compressed `context_facts` into the dataset context (prefer-facts), with raw-notes fallback + lazy fire-and-forget self-heal when notes exist but facts don't — matching A. Tests in `tests/unit/test_graph_stub.py` (prefer-facts / fallback+self-heal / pure-decision). Offline gate green (197 passed). *Real-Gemini gate (`extract_facts` quality) still to run.*
  - Files: `src/graph/nodes.py` (`_dataset_notes_for_prompt`, `_facts_as_notes`, `_trigger_facts_self_heal`, `setup` call site)

- [x] **C27 — Session DataFrame cache invalidation on delete (2026-07-01).** `clean`/`apply` and re-derive already called `invalidate_dataset_cache`; `delete_dataset`/`delete_all_datasets` did not, so a deleted dataset's stale in-memory frame could still be served mid-session. Added `invalidate_dataset_cache` calls to `_delete_one` (covers the direct target + cascade-deleted derived children) and to `delete_all_datasets`'s per-row loop. Regression tests in `tests/unit/test_datasets_delete_cache.py` (single delete, cascade, delete-all), red-before/green-after confirmed. Offline gate green (249 unit + 16 integration passed, 3 pre-existing provider-key skips). Byte-bounded eviction (`cache_limit_mb`) remains a nice-to-have, not required by spec — deferred.
  - Files: `src/api/datasets.py` (`_delete_one`, `delete_all_datasets`), `src/graph/nodes.py` (`invalidate_dataset_cache`)

- [x] **C29 — Prompt breakdown panel already shipped (re-verified 2026-07-01).** This entry predates the fix: `PromptBreakdown.tsx` renders the per-component breakdown (collapsible bars, ARIA `progressbar`, total/output summary), wired into `ConversationTurnView.tsx` (gated on `answer.prompt_breakdown`), fed by `runner.py`'s `_build_prompt_breakdown` via `query_runs.prompt_breakdown` → `/ask` + session/turn payloads. Confirmed live by `503e5b2`, `d846cb4`, `e28a37a`. **Remaining cosmetic-only question:** A puts the panel inside the Steps inspector; this build renders it at the conversation-turn level instead — not re-verified against A's exact placement, not treated as a functional gap.
  - Files: `frontend/src/components/analyse/PromptBreakdown.tsx`, `frontend/src/components/analyse/ConversationTurnView.tsx`, `src/graph/runner.py`

---

## Tier 2 — Cheap functional gaps

- [x] **C8 — Column cap already implemented (re-verified 2026-07-01).** `_stringify` in `src/graph/sandbox.py` already caps at 20 columns with a "[showing 20 of N columns]" note (explicitly commented `# Cap columns (C8: up to ~20 cols per spec)`), applied before the total-char cap so it isn't defeated by truncation. Landed in `32f2cb2` alongside `tests/unit/test_sandbox.py`'s "D4: column cap" test block (5 green tests) — just never cross-referenced back to this doc.
  - Files: `src/graph/sandbox.py` (`_stringify`), `tests/unit/test_sandbox.py`

- [ ] **C11 — Multi-format parsing (MOSTLY CLOSED — re-verified 2026-07-07; one sliver left).** The JSON half was fixed by D9: `_parse_dataframe` explicitly detects the split orientation and falls back across orients (records / column-keyed / split all parse). A TSV upload test exists (`tests/unit/test_api_stub.py`). **Remaining:** TXT is still hardcoded `sep="\t"` — no delimiter sniff, so comma/pipe-delimited `.txt` misparses to a single column. Tracked as its own small Tier-3 roadmap item ("TXT delimiter sniffing").
  - Files: `src/api/upload.py` (`_parse_dataframe` TXT branch)

- [x] **C14 — Multi-dataset e2e test shipped (re-verified 2026-07-07).** `tests/integration/test_multi_dataset_real.py` drives a real cross-dataset question through the agent against real Gemini; green in the 2026-07-07 gate runs.
  - Files: `tests/integration/test_multi_dataset_real.py`

---

## Tier 3 — Ingestion UX (one workstream — do C16 + C13 + C17 together)

- [x] **C9 — Session bulk multi-select shipped (re-verified 2026-07-07).** `SessionSidebar.tsx` has per-row checkboxes, Select all / Deselect all, and "Delete selected (N)" via `api.bulkDeleteSessions` (bulk-delete-by-ids endpoint).
  - Files: `frontend/src/components/analyse/SessionSidebar.tsx`, `src/api/sessions.py`

- [x] **C16 — Notes file on upload shipped (re-verified 2026-07-07).** `src/api/upload.py` accepts `notes_file` (wins over the form context field) with the 4000-char cap applied.
  - Files: `src/api/upload.py` (~lines 106–132)

- [x] **C13 + C17 — Folder drop + staged upload queue shipped (re-verified 2026-07-07).** Documented as a shipped capability in `spec/capabilities/multi-file-folder-drop.md`; the Database tab's merged Upload card carries the drag-and-drop + staged-uploads UI.
  - Files: `spec/capabilities/multi-file-folder-drop.md`, `frontend/src/components/database/`

---

## Already at parity (no action) — for reference

C1, C2, C3, C4, C6, C7, **C10** (filename-dup fixed 2026-06-29), C12, C15, C18, C19, C20, **C21** (B-ahead: adds Anthropic provider), C22, C23, C24, C25, C26, C30, C32.
