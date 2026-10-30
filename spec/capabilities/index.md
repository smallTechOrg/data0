# Capabilities Index

> One file per capability, IDs preserved from the source spec (C1–C32) plus C33/C34/C35/C36/C37/C38/C39/C40 added post-source (Phases 5/7/8/9/10/12/14/15), and C41–C47 (Phases 16–19). The source numbering **skips C5 and C28** — both are intentional gaps in the source list, not missing capabilities; no `C5` or `C28` file exists. The 45 capabilities below are the complete set. Each file states what it does, inputs/outputs, external calls, business rules, the phase that delivers it, and testable success criteria.

---

## Capabilities in This Project

| ID | Capability | Phase | File |
|----|-----------|-------|------|
| C1 | CSV / multi-format upload | 2 | [upload-ingest.md](upload-ingest.md) |
| C2 | NL Q&A ReAct loop | 2 | [nl-qa-react-loop.md](nl-qa-react-loop.md) |
| C3 | Multi-turn conversation history | 3 | [multi-turn-conversation.md](multi-turn-conversation.md) |
| C4 | Inline ECharts charts | 4 | [inline-charts.md](inline-charts.md) |
| C6 | Markdown → HTML answer rendering | 2 | [markdown-answer-rendering.md](markdown-answer-rendering.md) |
| C7 | Per-run token tracking | 2 | [token-tracking.md](token-tracking.md) |
| C8 | Expanded result display | 2 | [expanded-result-display.md](expanded-result-display.md) |
| C9 | Session management UI | 3 | [session-management.md](session-management.md) |
| C10 | Duplicate detection | 2 | [duplicate-detection.md](duplicate-detection.md) |
| C11 | Multi-format ingest | 2 | [upload-ingest.md](upload-ingest.md) |
| C12 | Dataset context notes injection | 2 | [dataset-context-notes.md](dataset-context-notes.md) |
| C13 | Multi-file / folder drop | 2 | [multi-file-folder-drop.md](multi-file-folder-drop.md) |
| C14 | Multi-dataset querying | 3 | [multi-dataset-querying.md](multi-dataset-querying.md) |
| C15 | Dataset deletion + cascade | 2 | [dataset-deletion-cascade.md](dataset-deletion-cascade.md) |
| C16 | Notes file on upload | 2 | [notes-file-on-upload.md](notes-file-on-upload.md) |
| C17 | Staged client-side upload queue | 2 | [staged-upload-queue.md](staged-upload-queue.md) |
| C18 | Token usage widget + daily stats | 2 | [token-usage-widget.md](token-usage-widget.md) |
| C19 | Automatic dataset selection | 3 | [auto-dataset-selection.md](auto-dataset-selection.md) |
| C20 | Early exit / force-finalize | 2 | [force-finalize.md](force-finalize.md) |
| C21 | Multi-provider LLM | 2 | [multi-provider-llm.md](multi-provider-llm.md) |
| C22 | Query timer + live progress bar | 2 | [live-progress.md](live-progress.md) |
| C23 | Agent steps inspector | 2 | [steps-inspector.md](steps-inspector.md) |
| C24 | NL data cleaning (preview + apply) | 4 | [nl-data-cleaning.md](nl-data-cleaning.md) |
| C25 | Derived-dataset persistence + lineage + staleness | 4 | [derived-datasets.md](derived-datasets.md) |
| C26 | Pre-flight clarification check | 3 | [preflight-clarification.md](preflight-clarification.md) |
| C27 | Session-scoped DataFrame cache + Parquet | 3 | [dataframe-cache-parquet.md](dataframe-cache-parquet.md) |
| C29 | Live context-window display | 3 | [context-window-display.md](context-window-display.md) |
| C30 | On-demand dataset notes generation | 4 | [dataset-notes-generation.md](dataset-notes-generation.md) |
| C31 | Semantic context compression | 4 | [context-compression.md](context-compression.md) |
| C32 | Collapsible conversation turns | 3 | [collapsible-turns.md](collapsible-turns.md) |
| C33 | Per-step reasoning | 5 | [per-step-reasoning.md](per-step-reasoning.md) |
| C34 | Theming — dark/light + accent + density | 7 | [theming.md](theming.md) |
| C35 | Fast Mode — a single latency toggle | 8 | [fast-mode.md](fast-mode.md) |
| C36 | External database connectors (PostgreSQL, BETA) | 9 | [external-db-connectors.md](external-db-connectors.md) |
| C37 | Suggested questions — session starters + clarification candidates | 10 | [suggested-questions.md](suggested-questions.md) |
| C38 | Multi-sheet Excel import (multi-tab workbooks) | 12 | [multi-sheet-excel.md](multi-sheet-excel.md) |
| C39 | Prompt-cache token accounting (honest discounted cost) | 14 | [prompt-cache-accounting.md](prompt-cache-accounting.md) |
| C40 | Agent-built dashboard (KPIs + charts + tables from a data file + NL command; drag-to-rearrange) | 15 | [dashboard-builder.md](dashboard-builder.md) |
| C41 | Priority-ranked dashboard insights (ranked KPIs/widgets, why-it-matters descriptions, chart-type rationale, spec v2) | 16 | [dashboard-insights-priority.md](dashboard-insights-priority.md) |
| C42 | Dashboard widget editing, field rebinding, regenerate | 17 | [dashboard-widget-editing.md](dashboard-widget-editing.md) |
| C43 | Dashboard-level filters | 17 | [dashboard-filters.md](dashboard-filters.md) |
| C44 | Dashboard templates + schema-bound reuse | 18 | [dashboard-templates.md](dashboard-templates.md) |
| C45 | External dashboard read API (spec + data) | 18 | [dashboard-external-api.md](dashboard-external-api.md) |
| C46 | REST API data source | 19 | [api-data-source.md](api-data-source.md) |
| C47 | SQL database data source | 19 | [sql-data-source.md](sql-data-source.md) |

> **C41–C47** extend C40 into a Power-BI-grade builder (Phases 16–19; the consolidated "Assumed decisions" for the whole series live in [dashboard-insights-priority.md](dashboard-insights-priority.md)). Power BI / Tableau export is explicitly out of scope. Capability count is now 45 (C1–C47 minus the C5/C28 gaps).

> **C28:** intentionally absent in the source numbering — no capability, no file.
> **C34** is a new addition (post-source-spec), numbered after the source's C1–C33 range — a pure-frontend capability with no LLM/backend involvement, added via the "add a capability" path.
> **C35** is a new addition (post-source-spec), numbered after C34 — a per-query latency toggle (backend + frontend), added via the "add a capability" path. See `spec/roadmap.md` → "Future / Backlog" for its origin and the resolved open questions.
> **C36** is a new addition (post-source-spec), numbered after C35 — a pluggable snapshot-import connector seam (PostgreSQL only, BETA/flag-gated), added via the "add a capability" path. See `spec/roadmap.md` → "Future / Backlog" → "External database connectors" for its origin and design rationale.
> **C37** is a new addition (post-source-spec), numbered after C36 — session-start "Try asking:" chips (a new session-less `GET /suggestions/starters`) plus refined candidate questions on a C26 clarification turn (same single pre-flight call), added via the "add a capability" path. It gets its OWN file because no existing capability file owns follow-up suggestions (`generate_suggestions` shipped inside Phase 3 and is documented only in `spec/agent.md`/`spec/api.md`); C26's file owns only the clarification gate.
> **C38** is a new addition (post-source-spec), numbered after C37 — a sheet picker for multi-tab `.xlsx`/`.xls` workbooks with one-dataset-per-sheet registration (a pure data-loading mechanism: zero new LLM calls, no graph changes, no migration), added via the "add a capability" path. It gets its OWN file rather than folding into C1/C11 because it introduces a new two-step API flow (`POST /upload` inspect variant + `POST /upload/sheets`) and a per-sheet dedup semantics that extends C10; the C1/C11 single-file contract is unchanged for single-sheet workbooks. Core model (picker + one-dataset-per-sheet) user-approved 2026-07-07; see `spec/roadmap.md` → Phase 12.
> **C39** is a new addition (post-source-spec), numbered after C38 — Phase A ("Lever 1") of the "Token economics" backlog entry: capture Gemini's `cached_content_token_count`, persist per-run `tokens_cached`, and show "X of Y from cache" plus an honest cache-discounted cost, added via the "add a capability" path. It gets its OWN file rather than folding into C7/C18/C29 because it spans all three (provider → state → DB → API → both widgets) and carries its own measured ground truth (the 2026-07-08 Step-0 spike: implicit caching already active, ~74% cache hit on iterations 2+). C7/C18/C29 are amended to reference it; Lever 2 (adaptive identity-only catalog) explicitly stays in the backlog. See `spec/roadmap.md` → Phase 14.
> **C40** is a new addition (post-source-spec), numbered after C39 — an agent that profiles one dataset and, from a natural-language command, emits a VALIDATED dashboard spec (KPI cards, charts, tables) rendered by the frontend as a drag-to-rearrange grid, added via the "add a capability" path. It gets its OWN file because it introduces a new table (`dashboards`), a new route family (`/datasets/{id}/dashboards`, `/dashboards/*`), a new UI tab, and a new agent pipeline (deterministic profile → one structured LLM call → strict validation → repair/fallback; widget data from a safe aggregation engine, NOT sandbox code). It reuses C1/C11/C38 ingest, the Phase 4 ECharts option builder, `LLMClient`, and the C15 cascade. Field-drag reconfigure, multi-dataset dashboards and export are deferred to Phase 16+. See `spec/roadmap.md` → Phase 15.

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer creates a new `<name>.md`, updates this index, flags dependencies, and self-reviews fit against the architecture and data model.
