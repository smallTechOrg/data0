# Roadmap

---

## What This Agent Does

The **Data Analysis Agent** is a local, single-user web app. The user uploads a CSV (or TSV/TXT/JSON/Excel) file through the browser and asks questions about the data in plain English. A ReAct loop (Reason + Act) powered by Google Gemini reasons over the data with pandas, iterating until it can give a confident natural-language answer with optional inline charts. No code or SQL required from the user. The agent tracks each step it took, supports multi-turn conversations scoped to a set of datasets, can autonomously produce new derived datasets, and shows its own token usage and reasoning.

## Who Uses It

Data analysts, product managers, and non-technical stakeholders who have structured data sitting in files and want answers without writing code or SQL. Their goal: upload a file once, ask questions in plain English, and get correct, explainable answers in seconds.

## Core Problem Being Solved

Today these users either learn pandas/SQL, wait on an analyst, or fight with spreadsheet formulas. The agent replaces that manual analysis loop: it does the reasoning and the pandas execution itself, shows its work step by step, and returns a plain-English answer with charts — so a non-technical user gets a correct, explainable result directly.

## Success Criteria

- [ ] A user can upload a CSV through the browser in under 5 seconds and see it appear as a dataset with row/column counts.
- [ ] A user can ask an aggregation / filter / comparison question and get a correct natural-language answer (verified against the real Gemini API) in under 30 seconds.
- [ ] The ReAct loop iterates with pandas and self-corrects on execution errors, terminating on a `FINAL ANSWER:` signal or a force-finalize (max iterations / consecutive errors) — it never crashes the request.
- [ ] Multi-turn conversation works: a follow-up question in a session sees prior turns and reuses the same datasets.
- [ ] With no API key set, the app auto-engages stub mode, shows a visible yellow banner, and stays fully usable offline with plausible canned answers (a guarantee in addition to the real-key path, never a substitute for it).

## What This Agent Does NOT Do (Out of Scope)

- No authentication / multi-user / accounts — single local user only.
- No database querying — files only (CSV/TSV/TXT/JSON/Excel).
- No proactive auto-insights or scheduled analysis — every analysis is user-initiated.
- No data egress beyond the configured LLM provider — uploaded data lives on local disk and SQLite.
- No TTL / auto-expiry of datasets — they persist until explicitly deleted.

## Key Constraints

- **Single-user, local.** One agent run at a time per request; live progress polled at ~1/s.
- **File size:** the ReAct loop must answer aggregation/filter/comparison questions on datasets up to 100 MB.
- **Latency targets:** upload < 5 s; question → answer < 30 s (real Gemini).
- **Provider:** Google Gemini is the live provider (key in `.env`). OpenRouter is an alternate. Stub mode auto-engages with no key.
- **Production DB is SQLite** (via SQLAlchemy 2.0 + Alembic). This is the chosen production database for this project — SQLite IS production here; tests use an isolated SQLite copy, which is correct, not a substitute.
- **Conversation cap:** a session is limited to 20 turns.
- **Context note cap:** dataset context notes ≤ 4000 chars; compressed facts ≤ 20 per scope.

> **Model:** `gemini-3.1-flash-lite` — verified at the Phase 2/3 real-key gate (no fallback needed). Recorded in README and `spec/architecture.md` → LLM provider design.
>
> **Assumed:** The source capability list (C1–C32) has no **C28** — it skips from C27 to C29. This is treated as an intentional gap in the source's numbering, not a missing capability. We preserve the source's IDs verbatim (no renumber) and document the gap in `spec/capabilities/index.md`. No `C28` file is created.

---

## Phases of Development

> Four phases, derived from the source's P1–P4. Phase 1 is an OFFLINE data-layer win verified by tests + migrations (no clickable page — that is expected and stated below). Phase 2 wires the ReAct loop through the FastAPI routes and the real Analyse-tab UI, gated against the **real Gemini via `.env`** per harness rules #6/#7. Phase 3 adds live sessions / pre-flight selector & clarification + the end-to-end real-key test and the model verify/fallback. Phase 4 adds charts + derived datasets + the Database-tab ER diagram polish.
>
> Every gate runs against the **production DB driver (SQLite via `AGENT_DATABASE_URL`)**. Phase 1's gate is OFFLINE (no key). Phase 2+ gates run against the **real Gemini key in `.env`** and assert response CONTENT, not just status. An offline stub suite (`tests/unit/`, zero env, in-memory SQLite, no network) ships alongside as an ADDITIONAL guarantee — the real-key gate is always authoritative.
>
> **Slices are disjoint by file path** so parallel code-generators never touch the same file. Dependencies are declared explicitly; default is independent.

### Phase 1 — Offline data layer (the 4-table schema, domain entities, settings)

- **Goal:** The full SQLite data model exists and migrates cleanly: the 4 tables (`datasets`, `query_runs`, `conversation_sessions`, `settings`) are added to `db/models.py`, reachable via `init_db()`, covered by an Alembic migration, mirrored by Pydantic domain entities, with the new settings fields (`openrouter_api_key`, `max_iterations`) added. Verified by unit tests + a real Alembic migration against SQLite. This is a backend-only phase — there is no clickable page yet (expected). A clearly-labelled non-functional two-tab UI shell makes the vision visible.

- **Independent slices (parallel build units):**
  - `slice-1a` (backend — data layer) — the 4 SQLAlchemy models extending the existing `Base`, the Alembic migration `0002_data_analyst_tables.py`, the Pydantic domain entities, the settings additions, and unit tests for all of it. **Deps: none.**
  - `slice-1b` (frontend — visual stub shell) — the two-tab app shell (Analyse / Database tabs) in `frontend/`, replacing the transform form, with every interactive surface rendered as a clearly-labelled NON-FUNCTIONAL placeholder. **Deps: none** (pure presentational; no API calls — labels say "coming in a later phase").

- **Key surfaces / files:**
  - `slice-1a` owns: `src/db/models.py` (ADD `DatasetRow`, `QueryRunRow`, `ConversationSessionRow`, `SettingRow`; keep `RunRow`), `alembic/versions/0002_data_analyst_tables.py` (NEW), `src/config/settings.py` (ADD `openrouter_api_key`, `max_iterations`; extend `llm_provider` valid values), `src/domain/dataset.py` + `src/domain/query_run.py` + `src/domain/session.py` + `src/domain/setting.py` (NEW), `tests/unit/test_models.py` + `tests/unit/test_settings.py` + `tests/unit/test_domain.py` (NEW). Does NOT touch `db/session.py` (its `init_db()` already builds all of `Base.metadata` — new models flow in automatically; the conftest `_isolated_db` likewise picks them up).
  - `slice-1b` owns: `frontend/src/app/page.tsx` (REPLACE transform form with the two-tab shell), `frontend/src/components/AppShell.tsx` + `frontend/src/components/StubBanner.tsx` + `frontend/src/components/analyse/*` + `frontend/src/components/database/*` (NEW, all non-functional placeholders), `frontend/src/lib/*` if needed. Never touches `src/`.

- **Gate command (OFFLINE — no key required):**

  ```bash
  uv run pytest tests/unit/ -q
  uv run alembic upgrade head
  uv run alembic current
  ```

  All three from the repo root. `pytest tests/unit/` must pass with **no env vars and no network**; `alembic upgrade head` must succeed against the configured SQLite DB; `alembic current` must show a revision (proving the 4 tables exist). The DB driver is the production one (SQLite via `AGENT_DATABASE_URL`).

- **How the user tests it (handoff seed):** From the repo root run the three gate commands above and confirm: unit tests green, `alembic upgrade head` says "Running upgrade 0001 -> 0002", and `alembic current` shows `(head)` (the current head revision). This is a **backend-only phase verified via tests + migrations — there is intentionally no clickable analysis page yet**, say so explicitly. Optionally run `python agent.py --run` and open `http://localhost:8001/app/`: the two-tab shell is visible but **every control is a labelled NON-FUNCTIONAL stub** ("Upload — coming in a later phase", etc.). Those stubs are the planned vision, not bugs.

### Phase 2 — ReAct loop + REST routes + real Analyse tab (single-dataset Q&A)

- **Goal:** The core path works end to end: upload a CSV, ask a plain-English question on a **single dataset (no sessions yet)**, the ReAct loop runs through `LLMClient` (real Gemini from `.env`), and the rendered Markdown answer + iteration/token counts + steps inspector appear in the Analyse tab. Stub mode auto-engages with no key.

- **Independent slices (parallel build units):**
  - `slice-2a` (backend — LLM providers) — extend `LLMClient`/factory to the multi-provider design: add `stub` and `openrouter` providers behind the uniform interface; auto-detect provider from whichever key is set; explicit `stub` when none; the stub branches on injected node tags. **Deps: none.**
  - `slice-2b` (backend — graph) — replace the `transform_text` graph with the ReAct `StateGraph`: `AgentState`, nodes `setup / plan_action / execute_action / finalize / force_finalize / handle_error`, edges, the sandbox namespace, the runner, prompts. **Deps: slice-2a** (the graph calls `LLMClient`; consume its public `call_model` interface — stub can stand in during dev, but the gate uses real Gemini).
  - `slice-2c` (backend — API) — the upload/datasets/ask/runs/stats/health routers + the `ok()`/`api_error()` envelope wiring and single-origin static mount. **Deps: slice-2b** for `/ask` (calls the runner) and `slice-1a` data layer (already merged). Upload/datasets/preview routes are independent of the graph.
  - `slice-2d` (frontend — Analyse tab) — wire the Analyse tab to the real API: upload card, Tables/datasets card, Conversation card (ask, rendered Markdown, steps inspector, token counts), stub banner driven by a `provider` flag. **Deps: slice-2c** (consumes the REST contract in `spec/api.md`; can be built in parallel against that contract and integrated at the gate).

- **Key surfaces / files:**
  - `slice-2a` owns: `src/llm/client.py` (extend factory), `src/llm/providers/base.py` + `src/llm/providers/stub.py` + `src/llm/providers/openrouter.py` (NEW), `src/llm/providers/gemini.py` (model default note only). `tests/unit/test_providers.py` (NEW).
  - `slice-2b` owns: `src/graph/state.py`, `src/graph/nodes.py`, `src/graph/edges.py`, `src/graph/agent.py`, `src/graph/runner.py` (REPLACE the transform graph in place), `src/graph/sandbox.py` (NEW), `src/prompts/plan_action.md` + `src/prompts/finalize.md` (NEW; the old `prompts/transform.md` is removed by this slice). `tests/unit/test_graph_stub.py` (NEW).
  - `slice-2c` owns: `src/api/__init__.py` (register new routers), `src/api/upload.py` + `src/api/datasets.py` + `src/api/ask.py` + `src/api/stats.py` (NEW), `src/api/health.py` (extend `/health` with `provider`), `src/api/runs.py` (ADD `/runs/current`; keep existing), `src/domain/*` request/response models as needed. `tests/integration/test_ask_real.py` + `tests/e2e/test_golden_path.py` (NEW, real Gemini). `tests/unit/test_api_stub.py` (NEW, offline). NOTE: this slice removes the boilerplate `/runs` POST contract only if it conflicts — otherwise leave it; the canonical analysis route is `/ask`.
  - `slice-2d` owns: `frontend/src/app/page.tsx`, `frontend/src/components/analyse/*` (REPLACE the Phase-1 stubs with real components for upload + tables + conversation), `frontend/src/lib/api.ts` (NEW). Never touches `src/`. The Database tab and the session sidebar stay labelled stubs in this phase.

- **Gate command (REAL Gemini from `.env`, per rules #6/#7):**

  ```bash
  uv run pytest tests/unit/ -q
  uv run pytest tests/integration/ tests/e2e/ -q
  ```

  The first line is the offline stub suite (zero env, in-memory SQLite, no network) — an additional guarantee. The second line is the **authoritative real-key gate**: it requires `AGENT_GEMINI_API_KEY` in `.env`, drives the full upload → ask → answer journey through `TestClient` against the real Gemini, and asserts on real response **content** (the answer is non-empty Markdown, the run status is `completed`, steps were recorded). Plus a **live-server smoke**: `python agent.py --run` (runs migrations + frontend build + starts uvicorn on :8001), then `curl http://localhost:8001/health` and one real `/ask` round-trip returning real AI output. The model is verified here (see `architecture.md`); 404 → fall back to `gemini-2.5-flash` and record it.

- **How the user tests it (handoff seed):** From the repo root run `python agent.py --run` (it builds the frontend and starts the server), then open `http://localhost:8001/app/`. Upload a small CSV (it appears under "Tables" with rows×cols), type a question like "What is the average of column X?" and click Ask. Expect: a spinner, then a rendered Markdown answer, iteration + token counts, and an expandable Steps inspector showing the pandas the agent ran. **Real surfaces:** upload, Tables list, ask/answer/steps, token counts, stub banner. **Labelled stubs (still):** the Database tab, the sessions sidebar, follow-up suggestions, charts, derived datasets — coming in Phase 3/4.

### Phase 3 — Live sessions, multi-turn, pre-flight selector & clarification, suggestions

- **Goal:** Multi-turn conversations scoped to datasets work: a session carries history, the pre-flight clarification check (C26) can ask a clarifying question, the dataset selector (C19) picks which datasets to load for multi-dataset questions, follow-up suggestions appear, and the session sidebar is fully functional. The end-to-end real-key test passes and the Gemini model is verified/fallback-confirmed.

  > **Superseded in Phase 6 (v0.4):** the pre-flight `select_datasets` (C19) selector and `src/prompts/select.md` were removed — dataset selection is now **agent-driven** (a metadata-only catalog + lazy load; see Phase 6 and [capabilities/auto-dataset-selection.md](capabilities/auto-dataset-selection.md)). Everything else this phase delivered — sessions, multi-turn history, the C26 clarification check, and suggestions — remains.

- **Independent slices (parallel build units):**
  - `slice-3a` (backend — sessions API) — `/sessions` CRUD + `/datasets/{id}/sessions`, session-scoped run creation, the 20-turn cap, multi-turn history assembly. **Deps: Phase-2 `/ask`** (extends it; same file, so this slice OWNS `src/api/ask.py` + `src/api/sessions.py` for Phase 3).
  - `slice-3b` (backend — pre-flight + graph-adjacent) — `check_clarification` (C26), `select_datasets` (C19), `generate_suggestions`, session DataFrame cache (C27) in `setup`. **Deps: slice-2b graph** (extends `setup`/runner; OWNS `src/graph/preflight.py` + `src/graph/suggestions.py` + the `setup` cache logic + `src/prompts/clarify.md` + `src/prompts/select.md` + `src/prompts/suggest.md`).
  - `slice-3c` (backend — memory API) — `/memory` GET/PATCH + the global-memory injection into `plan_action`. **Deps: none** beyond the data layer (`settings` table). OWNS `src/api/memory.py` + the memory-read helper.
  - `slice-3d` (frontend — sessions + conversation polish) — sessions sidebar (list/resume/rename/new/delete/bulk), clarification turns (amber, re-submit with `skip_clarification`), suggestion chips, collapsible turns (C32), live progress bar from `/runs/current`. **Deps: slice-3a + slice-3b** (consumes their REST contracts). OWNS `frontend/src/components/analyse/SessionSidebar.tsx` + conversation components.

- **Key surfaces / files:** `slice-3a` → `src/api/ask.py`, `src/api/sessions.py`, `tests/integration/test_sessions_real.py`. `slice-3b` → `src/graph/preflight.py`, `src/graph/suggestions.py`, `src/graph/nodes.py` (setup cache only), `src/prompts/{clarify,select,suggest}.md`, `tests/integration/test_preflight_real.py`. `slice-3c` → `src/api/memory.py`, `src/graph/nodes.py` is NOT touched by 3c (memory read is a helper in `src/graph/memory.py` NEW owned by 3c; 3b's `plan_action` imports it — declared dependency, 3b owns the import line, 3c owns the helper file). `slice-3d` → `frontend/src/components/analyse/*` only.
  - **Conflict note:** `src/graph/nodes.py` is touched by both 3b (setup cache) and indirectly by 3c's helper. Resolve by: 3b OWNS all edits to `nodes.py`; 3c only ADDS `src/graph/memory.py` and exposes `get_memory_block()`; 3b imports it. This keeps file ownership disjoint.

- **Gate command (REAL Gemini from `.env`):**

  ```bash
  uv run pytest tests/unit/ -q
  uv run pytest tests/integration/ tests/e2e/ -q
  ```

  The integration suite now includes a **multi-turn real-key test**: create a session, ask Q1, ask a follow-up Q2 that depends on Q1's context, assert Q2's answer reflects the prior turn (real Gemini content). Plus a clarification test (ambiguous question → `type: "clarification"`) and a selector test (two datasets → correct subset loaded). Live-server smoke re-run (`python agent.py --run` then `curl` `/health` + a real `/ask`). The Gemini model is confirmed here.

- **How the user tests it (handoff seed):** Run `python agent.py --run` and open `http://localhost:8001/app/`. Create a New session, upload two CSVs, ask a question — answer appears; click a follow-up suggestion chip; ask an ambiguous question and see an amber "Needs clarification" turn with a re-submit. Rename and resume sessions from the sidebar. **Real surfaces now:** sessions sidebar, multi-turn, clarification, suggestions, dataset selection, live progress, project-notes/memory modal. **Labelled stubs (still):** inline charts and derived-dataset/save_dataset features, the Database-tab ER diagram — coming in Phase 4.

### Phase 4 — Charts, derived datasets, Database-tab ER diagram

- **Goal:** Inline charts render from the agent's ECharts option JSON (via the `echart(...)` sandbox helper), the agent can autonomously persist derived datasets via `save_dataset` (with lineage + staleness + re-derive), NL data cleaning (preview + apply) works, on-demand dataset notes + compression run, and the Database tab shows the full ER diagram with inferred FK edges and the table-description panel.

- **Independent slices (parallel build units):**
  - `slice-4a` (backend — charts + derived datasets) — capture ECharts `option` JSON via `echart(...)` in `execute_action`, `save_dataset` in the sandbox, derived-dataset registration + lineage + staleness, `/datasets/{id}/re-derive`. **Deps: slice-2b graph** (OWNS the sandbox + `execute_action` chart capture + `src/graph/derived.py`).
  - `slice-4b` (backend — cleaning + notes/compression) — `/datasets/{id}/clean` + `/clean/apply` (C24), `/datasets/{id}/describe` → `describe.py` (C30), `compress.py` (C31). **Deps: data layer + LLMClient.** OWNS `src/graph/describe.py` + `src/graph/compress.py` + the clean routes in a NEW `src/api/datasets_ops.py` (so it does not collide with 2c's `src/api/datasets.py`).
  - `slice-4c` (frontend — Database tab + charts render) — the Database tab ER diagram (`renderERDiagram`, `_erFkLinks`), the table-description panel, inline chart rendering in conversation turns, derived/stale badges + re-derive button, clean modal. **Deps: slice-4a + slice-4b** REST contracts. OWNS `frontend/src/components/database/*` + chart-render components in `frontend/src/components/analyse/*`.

- **Key surfaces / files:** `slice-4a` → `src/graph/sandbox.py` (chart capture + save_dataset), `src/graph/derived.py` (NEW), `src/api/datasets.py` (ADD `/re-derive` — owned by 4a in Phase 4), `tests/integration/test_derived_real.py`, `tests/e2e/test_charts.py`. `slice-4b` → `src/graph/describe.py` (NEW), `src/graph/compress.py` (NEW), `src/api/datasets_ops.py` (NEW), `src/prompts/{describe,compress,clean}.md` (NEW), `tests/integration/test_clean_real.py`. `slice-4c` → `frontend/src/components/database/*`, `frontend/src/components/analyse/ChartRender.tsx`. Never touches `src/`.

- **Gate command (REAL Gemini from `.env`):**

  ```bash
  uv run pytest tests/unit/ -q
  uv run pytest tests/integration/ tests/e2e/ -q
  ```

  The e2e suite includes a **real-key chart test** (ask a question that yields a chart → assert an ECharts `option` JSON with a `series` key is captured and returned) and a **derived-dataset test** (a question that triggers `save_dataset` → a new derived dataset is registered with lineage). Plus a **visual smoke**: `python agent.py --run`, drive `/ask` to produce a chart and `curl` the page / API to confirm chart JSON and the ER-diagram dataset payload are present.

- **How the user tests it (handoff seed):** Rebuild and run; ask a question that warrants a chart (e.g. "show the distribution of column X") — an inline chart renders. Ask something that creates a new table (e.g. "create a cleaned version with nulls dropped and save it") — a Derived dataset appears under Tables with a green badge. Open the Database tab: the ER diagram shows each dataset as a card with inferred FK edges; click a card to see its description, keys, columns, and preview; edit context notes; click "Generate notes". **All surfaces are now real.** No remaining stubs.

### Phase 5 — Per-step reasoning

- **Goal:** Each ReAct step now carries a SHORT natural-language rationale, captured inline from the SAME `plan_action` LLM call (no extra calls, no added latency/cost), stored on each `action_history` entry, and shown next to that step's code in the Steps inspector. Existing execution is byte-for-byte unchanged; the offline stub suite stays green. Delivers C33 (see [capabilities/per-step-reasoning.md](capabilities/per-step-reasoning.md)). NO DB migration, NO new `AgentState` field.

- **Independent slices (parallel build units):**
  - `slice-5a` (backend — prompt + parse + tests) — instruct the model to emit an optional leading `REASONING:` line before the bare expression (the exact reply contract is in the capability file), parse it off `llm_response` in `execute_action` BEFORE `_extract_code` runs, store `reasoning` (default `""`) on each `action_history` step, and keep `_extract_code` producing today's identical bare expression. Parsing stays in `src/graph/nodes.py` (NOT `sandbox.py`). Plus a stub/unit test (reasoning parsed + stored; execution unchanged; bare-reply → `reasoning=""`) and a real-Gemini integration test (a real run records non-empty reasoning on ≥1 step). **Deps: none.**
  - `slice-5b` (frontend — inspector + type) — add `reasoning?: string` to the `AskStep` type in `frontend/src/lib/api.ts`, and render the per-step rationale next to each action in `StepsInspector.tsx`; when `reasoning` is absent/empty render NOTHING (no layout break). Builds against the agreed `AskStep` shape. Never touches `src/`. **Deps: none.**

- **Key surfaces / files (disjoint by path):**
  - `slice-5a` owns: `src/prompts/plan_action.md` (ADD the `REASONING:` instruction), `src/graph/nodes.py` (split the optional `REASONING:` line in `execute_action`; store `reasoning` on the step dict; `_extract_code` unchanged), `tests/unit/test_reasoning.py` (NEW, offline/stub — reasoning parsed + execution unchanged + bare-reply fallback), `tests/integration/test_reasoning_real.py` (NEW, real Gemini — non-empty reasoning on ≥1 step). Does NOT touch `src/graph/sandbox.py` (parsing lives in `nodes.py`). Does NOT touch the stub (`src/llm/providers/stub.py`) — its bare expression parses to `reasoning=""` under the contract.
  - `slice-5b` owns: `frontend/src/lib/api.ts` (ADD `reasoning?: string` to `AskStep` only), `frontend/src/components/analyse/StepsInspector.tsx` (render the rationale; graceful absence). Never touches `src/`.

- **Gate command (REAL Gemini from `.env`, per rules #6/#7):**

  ```bash
  uv run pytest tests/unit/ -q
  uv run pytest tests/integration/ tests/e2e/ -q
  ```

  The first line is the offline stub suite (zero env, in-memory SQLite, no network) — it must stay **fully green** (no new failures vs the measured baseline of 213 passed / 0 failed on `main`), including the new `tests/unit/test_reasoning.py`. The second line is the **authoritative real-key gate**: it requires `AGENT_GEMINI_API_KEY` in `.env` and includes `tests/integration/test_reasoning_real.py`, which drives a real upload → ask round-trip and asserts that at least one `action_history` step has non-empty `reasoning` (and that the run still completes with a non-empty answer and unchanged execution semantics).

- **How the user tests it (handoff seed):** From the repo root run `python agent.py --run` and open `http://localhost:8001/app/`. Upload a small CSV, ask a question that takes a few steps (e.g. "What is the average of column X, and which rows are above it?"), then expand the **Steps inspector** on the answer turn. Expect: under (or beside) each step's pandas code block, a SHORT one-line rationale explaining WHY that step was chosen. Steps with no rationale (e.g. an offline/stub run with `AGENT_GEMINI_API_KEY` unset) simply show the code with no rationale line and an unchanged layout — that absence is expected, not a bug. **Real surfaces:** the per-step rationale lines in the Steps inspector. No new stubs introduced.

### Phase 6 — Agent-driven dataset selection (always-on)

- **Goal:** The agent itself picks which datasets a question needs — the pre-flight `select_datasets` (C19) roundtrip and the manual Tables-checkbox override are BOTH gone. `setup` builds a metadata-only *catalog* of ALL workspace datasets (`{id, filename, alias, columns, notes}`, no frames read) into `dataset_context`; the sandbox namespace is **lazy** (`build_lazy_namespace`) so `df`/`df1`/`<alias>` load only on first reference. Only the datasets the agent actually touches are materialized, and the run records ONLY those loaded ids (`get_loaded_ids`) so the C15 cascade-delete tracks real dependencies. `selector_reasoning` is retained (payload + `query_runs` column) for compat but is always `null`/NULL. Always-on in both run modes (not gated by Fast Mode). Delivers the rewritten C19 (see [capabilities/auto-dataset-selection.md](capabilities/auto-dataset-selection.md)). NO DB migration, NO new `AgentState` field.

- **Independent slices (parallel build units):**
  - `slice-6a` (backend — graph + sandbox) — the lazy namespace (`build_lazy_namespace` + used-tracking `_loaded_ids`/`get_loaded_ids`/`release_loaded_ids`), the metadata catalog in `setup` (columns from `columns_json` + notes ONLY from cached `context_facts`, C31 — no frames read), the load-on-reference loader in `execute_action`, and the `save_dataset` parent-lineage rewire onto the loaded ids. Removes the `select_datasets` node from the graph. **Deps: none** beyond the existing graph. OWNS `src/graph/sandbox.py` + `src/graph/nodes.py` + the `AgentState` field docs in `src/graph/state.py`.
  - `slice-6b` (backend — pre-flight + runner + ask) — drop the `select_datasets` pre-flight call, rename `run_selector`→`run_clarification` (C26, first turn only), hand the runner ALL datasets as the catalog, and record only the loaded ids on the run; the session set becomes used + derived (no frozen set). Delete `src/prompts/select.md` and the stub's `<node:select>` branch. **Deps: slice-6a.** OWNS `src/graph/preflight.py` + `src/graph/runner.py` + `src/api/ask.py` + `src/llm/providers/stub.py` + `src/prompts/plan_action.md`.
  - `slice-6c` (frontend — drop manual scoping) — `ConversationCard`/`AnalyseTab` stop passing `selectedDatasetIds` as ask scope; `api.ask` drops the `dataset_ids`/`dataset_id` body fields; the Tables checkbox selection becomes bulk-actions-only (delete) with a renamed **Selected** filter tab. **Deps: slice-6b** `/ask` contract. OWNS `frontend/src/components/analyse/{ConversationCard,AnalyseTab,TablesCard}.tsx` + `frontend/src/lib/api.ts`.

- **Key surfaces / files:** `slice-6a` → `src/graph/sandbox.py`, `src/graph/nodes.py`, `src/graph/state.py`, `tests/unit/test_sandbox.py`, `tests/unit/test_graph_stub.py`. `slice-6b` → `src/graph/preflight.py`, `src/graph/runner.py`, `src/api/ask.py`, `src/llm/providers/stub.py`, `src/prompts/plan_action.md`, `src/prompts/select.md` (DELETED), `tests/unit/test_preflight_stub.py`, `tests/unit/test_providers.py`, `tests/integration/test_preflight_real.py`. `slice-6c` → `frontend/src/components/analyse/*`, `frontend/src/lib/api.ts`.

- **Gate command (REAL Gemini from `.env`, per rules #6/#7):**

  ```bash
  uv run pytest tests/unit/ -q
  uv run pytest tests/integration/ tests/e2e/ -q
  ```

  The offline stub suite stays **fully green** — the `select_datasets`/`<node:select>`/`_dataset_notes_for_prompt` tests are removed, `run_selector` is renamed to `run_clarification`, and two tests are ADDED: a lazy-namespace test (referencing `df`/`df1` loads on demand + records the id; untouched datasets never load) and an agent-picks/used-tracking test (three datasets, ask about one via the stub → only that dataset loads and the run's `dataset_ids_json` == `[that id]`). The real-key gate asserts a three-dataset question loads only the relevant dataset, that the catalog reads no frames in `setup`, and that the C15 cascade touches only actually-loaded datasets.

- **How the user tests it (handoff seed):** Rebuild and run; upload three unrelated CSVs. Ask a question about ONE of them — the answer appears and the **Datasets used** disclosure lists only that dataset (the agent never loaded the other two). The Tables checkboxes no longer affect which datasets a question uses — they drive bulk delete and the **Selected** filter tab only. **No manual dataset scoping remains.**

### Phase 7 — Theming: dark/light + accent + density

- **Goal:** The app shell gains a working light/dark toggle, a 4-color accent picker, and a 3-step density picker, all changing the whole app's visual appearance instantly and persisting across reload via `localStorage`. Delivers C34 (see [capabilities/theming.md](capabilities/theming.md)). **Pure frontend, no LLM involvement, no new API key, no DB migration, no backend touched at all** — this is the one phase in this roadmap whose gate does not require a Gemini key, because there is nothing in this capability that calls the LLM or the API. The mechanism is a single global CSS-variable remap of the app's existing hardcoded Tailwind color classes (in `frontend/src/app/globals.css`, confirmed NOT design-synced) plus new client-only controls — it does not rewrite any of the ~18 design-synced components (`.design-sync/config.json` → `componentSrcMap`), with one small, deliberate, documented exception in `ChartRender.tsx` to make the chart canvas itself theme-aware (see the capability file for exactly what and why).

- **Independent slices (parallel build units):**
  - `slice-7a` (frontend — controls + persistence + global remap) — the new `ThemeControls.tsx` component (theme toggle, accent picker, density picker) rendered from `AppShell.tsx`'s header; the new `frontend/src/lib/theme.ts` module (localStorage read/write + `data-theme`/`data-accent`/`data-density` application); the full CSS-variable remap added to `frontend/src/app/globals.css` (per the class-by-class table in [capabilities/theming.md](capabilities/theming.md)). **Deps: none.**
  - `slice-7b` (frontend — chart theme-awareness) — the documented, minimal, localized edit to the synced `frontend/src/components/analyse/ChartRender.tsx`: read the active theme's CSS variables via `getComputedStyle`, pass theme-derived background/text/legend/axis colors into `chart.setOption(...)` on init AND on theme change (via a listener/observer on `document.documentElement`'s `data-theme` attribute), and replace the hardcoded `backgroundColor: '#fff'` in the `getDataURL` calls (`downloadImage`, `copyPng`) with the current theme's surface color. **Deps: slice-7a's CSS variables must exist** (7b reads the same `--surface`/`--text`/etc. custom properties 7a defines in `globals.css`) — genuinely a soft ordering dependency on the variable *names*, but the files touched are fully disjoint (`ChartRender.tsx` vs `ThemeControls.tsx`/`theme.ts`/`globals.css`), so both slices can be generated concurrently as long as the variable-name contract in the capability file is followed by both; integration is verified at the gate, not serialized at build time.

- **Key surfaces / files:**
  - `slice-7a` owns: `frontend/src/components/ThemeControls.tsx` (NEW), `frontend/src/lib/theme.ts` (NEW), `frontend/src/components/AppShell.tsx` (ADD: render `<ThemeControls />` in the header's right-hand control cluster; apply the theme on mount), `frontend/src/app/globals.css` (ADD: the full CSS-variable remap, all `data-theme`/`data-accent`/`data-density` variable definitions and the per-class override rules). Never touches `src/` or any file in `componentSrcMap`.
  - `slice-7b` owns: `frontend/src/components/analyse/ChartRender.tsx` ONLY (the documented synced-file exception — theme-aware `setOption` + theme-change listener + non-white export/copy background). Never touches `src/`, never touches any other frontend file.

- **Gate command (OFFLINE — no LLM key required; this phase makes zero LLM/API calls):**

  ```bash
  cd frontend
  npm run lint
  npm run build
  ```

  Both run from `frontend/`. `npm run lint` must be clean (no new ESLint errors introduced by `ThemeControls.tsx`, `theme.ts`, or the `ChartRender.tsx` edit). `npm run build` must succeed (Next.js static export to `frontend/out/`, the same build the `python agent.py --run` launcher runs) — this is the only automated check available for this phase, since the frontend toolchain (`frontend/package.json`) has no component/unit test runner (`dev`/`build`/`start`/`lint` are the only scripts). **There is no automated visual-regression check in this repo.** Confidence for this phase rests primarily on the live UI smoke described below (toggle actually flips colors on real rendered pages, chart actually re-themes), driven manually or by qa-auditor, NOT on the build/lint gate alone — say so explicitly when reporting this phase's gate result.

- **How the user tests it (handoff seed):** From the repo root run `python agent.py --run` (builds the frontend, starts the server) and open `http://localhost:8001/app/`. In the header's right-hand control cluster (next to the "Live" badge / "📝 Project notes" button) click the **theme toggle** (sun/moon icon) — the whole app (header, cards, panels, sidebar, text, borders) should flip from light to dark; nothing should render unstyled or blank. **Reload the page** — the dark choice should still be active (persisted via `localStorage`, not lost). Click each of the 4 **accent swatches** — the header bar / primary buttons / active-tab chrome should recolor, while the green (derived-dataset) and amber (stale-dataset / clarification) tints on the Tables card should stay their normal tint, unaffected by the accent choice. Click through the 3 **density options** — spacing on the Tables card rows and the conversation thread should visibly tighten/loosen. Ask a question that produces an inline **chart**, then toggle the theme with the chart on screen — the chart's background and text/axis/legend colors should re-theme along with the rest of the page (it should NOT stay a fixed white square in dark mode); then use the chart's **Copy** or **PNG/JPEG** export button in dark mode and confirm the exported/copied image's background matches the current theme rather than being forced to white. **Nothing in this phase is a stub — every control shipped here is fully working the first time you test it.**

---

## Future / Backlog (not yet scheduled)

Candidate features captured for a later phase — not built yet, no gate defined.

- **Token economics: prompt-cache accounting + on-demand dataset schemas (agent discretion).** Two distinct wins hiding behind one symptom — the C29 prompt-breakdown reporting 16K–24K input on questions that touch a *single* dataset. **Diagnosis (this conversation, 2026-07-01):** the breakdown is *cumulative across ReAct iterations* (`_build_prompt_breakdown` in `src/graph/runner.py` scales cumulative per-bucket chars to the summed provider `tokens_input`). Divide by the on-screen iteration count and every query collapses to the SAME ~8K per-call profile (payments query 24,116 ÷ 3 iters ≈ 8,039/call; chart query 16,326 ÷ 2 iters ≈ 8,163/call), of which **~99.6% is a byte-identical stable prefix** (`[tag, datasets, memory, history, question]`, per `_PLAN_SECTION_ORDER`) re-sent every iteration because each ReAct step is a fresh *stateless* LLM call. **The dominant cost driver is re-transmission, not size** — the lean catalog (C33) already made the catalog tight (~245 tokens/dataset); we just pay for it N times. This splits into two orthogonal levers:
  - **Lever 1 — prompt-cache accounting (lowers COST, not the COUNT).** Gemini's `usage_metadata.prompt_token_count` — the number we record and display — counts cached tokens at FULL value; the discount is applied silently in billing. So caching will NEVER shrink the C29 bars (they stay 24K); it only makes the repeated tokens cheaper. Worse, we can't even tell whether caching is happening: the provider reads only `prompt_token_count`, never `cached_content_token_count` (`src/llm/providers/gemini.py`, ~line 26). Gemini 3.x Flash caches *implicitly by default*, and within a run iterations 2..N send an identical ~8K prefix seconds apart (a textbook implicit-cache hit) — so it is probably ALREADY saving money invisibly. And the cost display prices the raw `prompt_token_count` at the full input rate (`src/api/stats.py` + `price_input_per_million` in `src/api/settings.py`) with no cache discount, so **if implicit caching hits, the displayed cost is overstated.** Fix = capture `cached_content_token_count`, price cached tokens at the discounted rate (~0.25× for Gemini implicit cache), and surface "X of Y served from cache" + an honest cost in the breakdown.
  - **Lever 2 — identity-only catalog, columns on demand (the "discretion" — the ONLY thing that shrinks the bars).** The catalog ships ALL workspace datasets' columns every iteration even when the question touches one — the original "no discretion / no compression on which datasets to access" complaint. Change the catalog line to identity-only (id / filename / alias / shape + 1-line note, NO columns); the agent pulls `df1.columns` only for the datasets it drills into (an affordance `src/prompts/plan_action.md` already advertises). Cuts the per-call catalog from ~2,940 to ~600 for a 12-dataset workspace, on EVERY call including iteration 1 (which caching cannot help). **Risk:** a cold single-dataset question may cost one extra inspection iteration, so it is a net win only once a workspace has several datasets — make it **adaptive** (inline columns when few datasets, identity-only when many). Extends C19/C33 ([capabilities/auto-dataset-selection.md](capabilities/auto-dataset-selection.md)).
  - **Sequencing (measure before building):**
    - **Step 0 — measurement spike (~30–45 min, cheap, possibly throwaway):** capture `cached_content_token_count` in the provider, run one real query, read the number. This single fact FORKS the plan — it tells us whether implicit caching is already hitting (→ Lever 1 collapses to "just fix the cost display") or not (→ explicit caching is real work; first confirm `gemini-3.1-flash-lite` even supports `CachedContent`).
    - **Phase A — caching productized (~2–3 hr):** persist cached tokens (new `query_runs.tokens_cached` column + Alembic migration), thread provider → runner → API → frontend, honest cost with the cache discount, "X of Y cached" in the C29 widget + the token-usage sidebar, plus tests.
    - **Phase B — Lever 2 discretion (~2–3 hr, variable):** adaptive identity-only catalog in `setup` / `_catalog_block`, prompt guidance, spec update, unit tests + a real-Gemini quality eval (confirm answer quality holds AND the iteration count does not balloon — the eval loop is the variable cost).
  - **Interlocks with:** Fast Mode below (both target loop cost — Fast Mode's "truncate action_history" and "tighten max_iterations" bullets attack the SAME per-iteration re-transmission from the roundtrip-count side); the C29 prompt-breakdown widget (Lever 1 adds a cached-tokens component to it); and C19/C33 catalog (Lever 2 extends them).
  - **Open questions:** cache-discount multiplier as a hard-coded constant vs a settings field (provider-specific — Gemini implicit ~0.25×, Anthropic cache-read ~0.1×); whether `gemini-3.1-flash-lite` supports explicit `CachedContent` at all; the adaptive-catalog dataset-count threshold; whether to show a cached-vs-fresh split in the C29 widget so the saving is visible. Build-effort note: coding-agent settings sized as Sonnet / medium for the spike + plumbing, Opus / high for the cost-accounting correctness (cross-provider cached-token semantics) and the Lever 2 design + eval.
- **Fast Mode — a single latency toggle (fewer tokens/roundtrips, NOT model switching).** One user-facing switch that trades a little answer depth for speed by sending the LLM *less work*, leaving the model/provider choice to the user's Settings (deliberately decoupled from the mode). Loop latency is dominated by (a) the number of LLM roundtrips and (b) sequential output generation — not input size — so the switch targets those. When ON it:
  - **Tightens `max_iterations`** (default 12 → a tighter cap) for the request only — the dominant lever, since each iteration is a full roundtrip. Overrides the settings/DB value.
  - **Skips pre-flight clarification (C26)** — no clarifying-question roundtrip; proceed on the best guess. Trades a better median latency for the occasional wrong guess that costs a re-ask.
  - **Skips follow-up suggestions** (`generate_suggestions`) — drops one post-answer roundtrip per query.
  - **Truncates each action result before it re-enters `action_history`** (e.g. ~500 chars) — the transcript is the fastest-growing prompt bucket (C29 `action_history`), so this is the one input cut that compounds across iterations.
  - **Asks for shorter answers** — a prompt-level brevity instruction only (no hard `max_output_tokens` cap, by decision: a hard cap risks mid-sentence truncation).
  - **Disables the forced-chart retry** — keeps charts but drops the `wants_chart`/`chart_force_count` guardrail's forced extra iteration, so a chart request can't blow through the tightened budget (best-effort chart, no forced loop).
  - **Considered and rejected:** switching model/provider (the user owns that), a hard output-token cap, and lowering reasoning/thinking effort (would couple the mode to model capabilities).
  - **Open questions:** per-query override vs a global default; where the toggle lives (Analyse composer vs Settings); the exact tightened `max_iterations` value; whether to surface the before/after token delta in the C29 prompt-breakdown widget so the saving is visible.
- **Theming: dark/light + accent + density.** Scheduled and specified — see **Phase 7** above and [capabilities/theming.md](capabilities/theming.md) for the full mechanism (CSS-variable remap of `globals.css`, the three controls, localStorage persistence, and the `ChartRender.tsx` exception). No longer an open backlog item.
- **Soft-delete + recovery for datasets & sessions (data-safety hardening).** Today `DELETE /datasets/{id}` and session deletes are **hard deletes that cascade** — deleting a dataset also destroys its derived datasets (C25 lineage) and any sessions scoped to it, irreversibly. This is the sharpest data-loss edge in the app: one click can wipe a whole lineage with no undo. Borrow tamo's soft-delete discipline (`tamo-data-analysis-agent-v0.2`, `Database.version` + `deleted_at`/`deleted_version` + partial-unique indexes `WHERE deleted_at IS NULL`).
  - **Mechanism:** add a `deleted_at` (nullable) column to `datasets` and `conversation_sessions` (and optionally `query_runs`); delete routes set `deleted_at = NOW()` instead of removing rows; all read/list queries filter `deleted_at IS NULL`; uniqueness (e.g. dataset `content_hash` dedup, C10) becomes a partial index on active rows only, so re-uploading a soft-deleted file inserts a fresh active row.
  - **Recovery surface (optional, later):** a "Trash"/restore affordance, or at minimum a way to un-delete via DB. Even without UI, the soft-delete alone removes the irreversible-loss risk.
  - **Why it's the top pick:** unlike DuckDB/connectors below (feature-expansion, or gated on evidence), this is pure hardening — small, self-contained, low-risk, and directly prevents accidental permanent data loss. Rationale from the tamo-comparison analysis (this conversation, 2026-07-01): the one clear production-grade win among the tamo borrows.
  - **Files (indicative):** `src/db/models.py` (add columns + partial indexes), an Alembic migration, `src/api/datasets.py` + `src/api/sessions.py` (flip delete to soft-delete; filter reads), the cascade helpers in `src/graph/derived.py` (soft-delete derived children instead of hard-deleting). Frontend delete flows unchanged (still call the same endpoints).
- **DuckDB query engine for large files (scale hardening — GATED on evidence).** Addresses a real ceiling: the pandas ReAct loop loads **entire files into memory** as DataFrames (`setup` node), but the spec targets files up to 100 MB. DuckDB is an in-process engine (`import duckdb`, no server) that can query Parquet/CSV **lazily off disk** and hand results back as DataFrames (`.df()`), so it slots into the existing pandas world rather than replacing it.
  - **The win is RAM, NOT speed — don't let the speed pitch mislead you.** DuckDB is not a storage format; data stays as Parquet on disk. The comparison is *how you read it*. Today `pd.read_parquet` decompresses the **whole table into RAM** (typically 2–10× the Parquet file size); DuckDB scans the Parquet with column/row pushdown, streams, and can **spill to disk** instead of OOM-ing (pandas just crashes). So for selective queries DuckDB uses **less** RAM, and it degrades gracefully on huge files. Query *speed* is faster on paper (vectorized + multi-threaded vs pandas' single thread) **but is irrelevant here**: this app's latency is dominated by LLM roundtrips, not pandas (a 100 MB aggregation is sub-second to a few seconds), so faster queries shave ~nothing off user-perceived time. Ingestion is unchanged (or slightly faster if DuckDB does the CSV→Parquet).
  - **⚠️ Do NOT build speculatively — measure RAM first (not speed).** Load the largest realistic file, watch **peak RAM** on a heavy aggregation. If it's comfortable, skip this entirely — DuckDB buys you little. Only if you're actually hitting a memory ceiling is it worth it. (Highest *ceiling* improvement but also the biggest architectural change, so it must be evidence-driven.)
  - **Least-invasive shape (modest payoff):** a DuckDB-backed read path in `setup`/sandbox that materializes only what's queried (`duckdb.query("SELECT … FROM 'file.parquet'").df()`), keeping the agent's pandas contract intact. **Caveat:** this is really just *smarter loading* — pandas still does the compute, so you only save RAM *if you push projections/filters into the DuckDB read*, and you get ~no speed change.
  - **More-invasive shape (full payoff, separate/later):** give the agent a real **SQL action** so DuckDB *computes* the query and can hit huge external/attached tables *without* materializing them — this is where the full RAM **and** speed wins actually live, but it changes the agent's tool contract, so treat as its own step, not part of the first cut.
  - **Interlocks with:** the External-DB-connectors item below (DuckDB `ATTACH … READ_ONLY` is how tamo reaches Postgres) and Fast Mode (both target loop cost). Reference engine usage: `tamo-data-analysis-agent-v0.2` (`src/tools/mcp/server.py`, DuckDB over Parquet + `ATTACH`).
- **External database connections via MCP** (adapted from `tamo-data-analysis-agent-v0.2`). Today datasets are file uploads only (CSV/Excel/JSON → CSV+Parquet on disk). Add the ability to connect an **external database** (PostgreSQL first, read-only) as a data source the agent can query, surfaced through the **Model Context Protocol (MCP)**. Shape it after the tamo design:
  - **Safe-port decision (from the tamo-comparison analysis, this conversation).** This is **feature-expansion, not production-hardening** — schedule it when you want the feature, not as a prerequisite for "production grade." The **least-invasive port** keeps the pandas agent completely untouched: the connector's job is to **return a DataFrame** (via `pd.read_sql` or DuckDB `ATTACH READ_ONLY` → `.df()`), so from the `setup` node's perspective an external table is "just another `df`" and the sandbox/prompts/all 30 capabilities stay as-is. The existing disk-load logic becomes the built-in `parquet` connector. Keep it an independent slice: new `src/connectors/*`, and the *only* existing file touched is the load path in `setup` (`src/graph/nodes.py`). Note: MCP *connectors* (reading external DBs) are separable from MCP *exposure* (serving your datasets to third-party MCP clients) — the latter is a product-direction bet, not needed for connectors to work.
  - A **`DatasetConnector` seam** (`tools/connectors/` in tamo): pluggable connectors behind a uniform interface — `parquet` (internal, existing) and `postgres` (external, BETA, flag-gated). Adding a source type = writing a connector, not touching the agent.
  - **Read-only querying** of the external DB (tamo uses DuckDB `ATTACH … READ_ONLY`); a `connection_check()` runs BEFORE persisting a connection. No writes ever leave the agent.
  - **MCP exposure**: each connected source becomes addressable via an MCP JSON-RPC surface (`tools/list · tools/call · resources/list · resources/read`, MCP 2025-06-18) so the agent — and external MCP clients — query it through standard MCP tools; an in-process FastMCP pool serves the agent a generic `query` tool.
  - **Scope/constraints to decide:** which DBs beyond Postgres; credential storage + secret hygiene (connection strings are secrets — never logged/committed); flag-gating the BETA; how a DB source appears in the Tables/Database tabs alongside uploaded datasets; and reconciling tamo's DuckDB SQL engine with this repo's pandas ReAct loop (likely: the connector exposes tables the sandbox can `pd.read_sql`/DuckDB-query, or the ReAct loop gains a SQL action). Reference implementation: `c:\Users\verma\workspace\tamo-data-analysis-agent-v0.2` (`src/tools/connectors/`, `src/tools/mcp/`, `spec/product/02-architecture.md`).
