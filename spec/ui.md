# UI

> Built in the existing Next.js `frontend/` (React 19 / TSX), single-origin, served at `/app` on port 8001. Replaces the skeleton's transform form in `frontend/src/app/page.tsx`. Same information architecture and UX as the source design (Analyse + Database tabs). All API calls go through `frontend/src/lib/api.ts` to the root REST routes. **Phase-by-phase:** Phase 1 ships every surface as a clearly-labelled NON-FUNCTIONAL stub; Phase 2 makes upload + Tables + conversation real; Phase 3 makes sessions/clarification/suggestions real; Phase 4 makes charts + the Database tab real.

---

## UI Type

Web dashboard (single-page, two tabs), served single-origin by FastAPI.

## Tech Stack

Next.js 15 + React 19 + TypeScript (existing `frontend/`), static-exported to `frontend/out/` and mounted at `/app` (UI at `http://localhost:8001/app/`; the `agent.py --run` launcher builds it). `echarts` (tree-shaken `echarts/core`, ~0.64 MB) for inline charts (Phase 4). `react-markdown` + `remark-gfm` for client-side answer rendering. SVG for the ER diagram.

## Shell & Global Chrome

- **Header:** app name + tagline; a **Project notes** button opens the global-memory modal (memory/C29); a **yellow stub-mode banner** is shown when `GET /health` reports `provider == "stub"` (so demo output is never mistaken for real output); a **theme toggle** (C34, Phase 7) — a single light/dark icon button — sits in the header's right-hand utility area alongside the Live badge and Project-notes button. Accent (indigo) and density (compact) are fixed product decisions with no picker UI — see [capabilities/theming.md](capabilities/theming.md).
- **Layout:** two-panel responsive shell; ≤960px stacks panels, ≤640px stacks cards.
- **Tabs:** `[Database]` (default) and `[Analyse]`.

## Views / Screens

### Screen: Analyse tab

**Purpose:** upload data, ask questions, read answers, manage sessions.

**Key elements:**
- **Sidebar — Sessions panel** (C9): list with name / first-question, turn count, absolute timestamps ("Started {date·time} · Updated {date·time}"); checkbox bulk-select; click to resume; inline rename/delete icon buttons; **+New**; **Delete selected**; **Clear all** (modal). Data from `GET /sessions`; mutations via `PATCH /sessions/{id}/name`, `DELETE /sessions/{id}`, `DELETE /sessions`.
- **Sidebar — Token usage widget** (C18): model name; Last query In/Out/Cost and Today In/Out/Queries/Cost from `GET /stats/daily`; storage row = dataset count + total rows; client-side pricing table ("N/A" unknown). Costs are **cache-discounted** (C39): cached tokens priced at 0.25× for Gemini, and an **"X of Y tokens served from cache"** line renders under Last query when `tokens_cached > 0` (never at 0 — small workspaces legitimately show no line; see [capabilities/prompt-cache-accounting.md](capabilities/prompt-cache-accounting.md)). Plus the **C29 token-budget bar at rest**.
- **Datasets card — "Tables":** filter tabs All | Uploaded | Derived | Selected; per row checkbox (drives **bulk actions only** — the selection does NOT scope analysis; dataset selection is agent-driven, C19) + filename + rows×cols + format + a **columns** icon toggle + a **Clean** (broom) icon (uploaded only); **origin/stale is shown by the whole-row tint** — uploaded = neutral (no tint), derived = green, stale = amber (no text badge); **Re-derive** on stale rows. The **Selected** tab narrows the list to the checked rows. **Deletion is a bulk action** in the selection bar (no per-row delete): an always-present **Select all** (disabled when everything is selected) + **Clear** (when any selected), then **Delete selected (N)** with an inline confirm → `DELETE /datasets/{id}` for each checked dataset; a right-aligned "N dataset(s) selected" count. Re-fetch `GET /datasets` after each completed query to surface new derived sets (C25).
- **Upload card** (C1, C11, C13, C16, C17, C38): drag-drop files AND folders (reads `_notes`/`context`/`readme` as folder notes, `<stem>.notes.txt` per file); **Choose files**; staged file map (rename, typed notes, attach notes file, remove); **Upload N file(s)** ≤3 concurrent with per-file states; **409 → "Use existing / Upload anyway"** inline resolver (`force=true`). Calls `POST /upload`. **Sheet picker (C38, Phase 12):** a staged `.xlsx`/`.xls` whose upload returns the `type:"multi_sheet"` inspect variant transitions its staged row to a **"Pick sheets"** state — an inline checklist (the C36 pick-tables pattern, one row per sheet: checkbox + sheet name + rows×cols; non-empty sheets pre-checked; empty sheets disabled with an "empty" tag) + an **"Import N sheet(s)"** button → `POST /upload/sheets`. Per-sheet results render inline: ✓ rows×cols on `ok`, the existing "Use existing / Upload anyway" resolver on `duplicate` (retries that sheet with `force:true`), the message on `error`; the row leaves the queue once every selected sheet is resolved. A single-sheet workbook never shows the picker (imports directly, exactly as today). Each imported sheet appears under Tables as its own dataset named `workbook.xlsx — Sheet`.
- **Conversation card** (C2, C3, C6, C7, C22, C23, C32): thread (`role="log"`, `aria-live="polite"`); per turn = question (blue) + an "Asked at {time}" + a response-time "**took Xs**" (from the answer's `duration_ms`), optional **Best effort** badge (`is_best_effort`), the answer Markdown **rendered client-side** (sanitised via `react-markdown` + `remark-gfm`; NOT the server's `answer_html`), iteration + token counts, **Datasets used** disclosure, **Steps inspector** (collapsible; per-step dark code block + result/error + Copy; red **Error** badge), 2–3 follow-up **suggestion chips** (`suggested_questions`) that **drop the question into the composer** (focus + caret to end) for the user to edit/confirm — they do NOT auto-submit (the `SuggestionChips` component takes an optional `label` prop, default "Follow-up suggestions"). Two more chip surfaces (C37): an **empty conversation** with ≥1 dataset shows up to 3 **"Try asking:" starter chips** (from `GET /suggestions/starters`, fetched once per Analyse-tab mount and memoized — a "New session" reset reuses them; fetch failure/empty → the block silently doesn't render, never blocking the composer), and the **latest live clarification turn** shows its refined-candidate chips ("Or try a refined question:", from the clarification response's `suggested_questions`; resolved/reloaded clarification turns show none — candidates are live-only). Both reuse the same chips component and fill-the-composer behavior; two session-level export buttons — **Export MD** (downloads a full Markdown LOG of the whole conversation — per turn: prompt, any clarification, asked-at + response time, status, iterations, tokens, datasets used, the answer, the backend code steps (action + output), and the prompt breakdown; with a header carrying the active model + total tokens) and **Export PDF** (opens a self-contained HTML rendition of the same data in a new window and triggers the browser's print dialog so the user can save as PDF — no extra packages; uses `window.open` + `window.print()`); **clarification turns** amber with "Needs clarification" → re-submit `skip_clarification:true` (C26); **C32** per-turn collapse/expand + Collapse all / Expand all (`sessionStorage`). Input: question textarea (Enter submit, Shift+Enter newline), **Ask** (spinner/disabled while running), **Stop** (shown while running — aborts the `/ask` request via `AbortController` AND `POST`s `/runs/{run_id}/cancel` so the agent loop wraps up server-side with no further LLM calls; the run id comes from the progress poll, so the server-side cancel takes effect once the run is underway — an early Stop still aborts the client immediately and renders the turn as "Stopped."), Progress row (elapsed timer + Step N/M bar from `GET /runs/current`; "Checking…" during C26). Calls `POST /ask`.
  - **Answer export toolbars** (in each rendered answer): every inline **chart** gets a small **Copy** (PNG → clipboard, via ECharts `chart.getDataURL()` at 2× pixel-ratio + `ClipboardItem`; falls back to a PNG download where the clipboard-image API is blocked) / **PNG** / **JPEG** toolbar; every rendered Markdown **table** gets a **Copy** (TSV — pastes straight into Sheets/Excel) / **CSV** (download) toolbar, reading the real rendered cell text. Helpers live in `frontend/src/lib/exporters.ts`; chart export lives in `ChartRender.tsx`.

**Actions available:** upload, ask, stop, resume/rename/new/delete sessions, edit memory, export session (Markdown or PDF), copy/export a chart (PNG/JPEG) or a table (TSV/CSV), re-submit clarification, drop a suggestion into the composer.

### Screen: Database tab (session-scoped data universe)

**Purpose:** explore the data universe, schema, lineage, and per-dataset details.

**Key elements:**
- **Header:** session name + "N uploaded / M derived" + **Clear database** (danger → `DELETE /datasets`).
- **Schema panel — full ER diagram** in SVG (`<ERDiagramPanel>`): each dataset is a table card listing columns (first 8 + "+N more", zebra rows, dtype color dot: number=blue, text=purple, date=amber, boolean=green, other=grey, plus an **in-card PK/FK badge** beside the dtype dot); uploaded = blue header, derived = green header + "derived" tag. Inferred FK edges via **`_erFkLinks(datasets)`** — the single source of truth for the edges, the in-card badges, AND the right-panel PK/FK badges: links columns ending `_id` shared by ≥2 tables, a `zip_code_prefix` family normalized to a geolocation hub, exact-name shared specific columns, with a denylist of generic columns; canonical PK table chosen by filename. **Hybrid layout:** a **radial tree** when a hub table has FK-degree ≥ 3 (hub centred, neighbours fanned out on concentric rings by subtree leaf count), else a horizontal **serpentine grid** (BFS order, biased wider than tall) for small / hub-less schemas. Edges are **smooth cubic-bezier** connectors anchored at each end's PK/FK **column row**, leaving/arriving horizontally and drawn **BEHIND the cards** (an overlapping curve passes behind a card, not through it); crow's-foot at the many/FK end, tick at the one/PK end; derived edges dashed green; hover-only join-key pill. Overlap-resolution pass + auto-fit (measures the real rendered bbox). Controls: **Fit / + / −**, a **"Reset layout"** button (clears any dragged card positions and re-fits; disabled until a card has actually been dragged), a live **"Stretch"** slider (horizontal x-stretch, 1–2.5×), a live **"Ring gap"** slider (radial ring spacing, 0–200), and a **"Details"** toggle that collapses the sibling Table-description panel so the diagram spans the full width; drag-pan, wheel-zoom (0.15×–3×) **anchored at the mouse cursor** (the +/− buttons anchor at the viewport center) so the content under the anchor point stays fixed on screen rather than drifting toward the top-left corner; click card → `onSelect(id)` (suppressed if the pointer moved past a small threshold, i.e. a drag, rather than a plain click); **click-drag a card to reposition it** — session-only (component state, not persisted), overrides the auto-layout position for that card, survives an incidental re-layout (resize, origin filter toggle) but not a page reload, and its connected edges follow it live; hover highlights its relationships and dims others to ~0.3. In dark mode the canvas itself renders pure black (a deliberate exception to the standard dark-surface color), while the surrounding card chrome (header, toolbar, border) stays on the normal dark theme.
- **Table Description panel:** filename + origin/stale badges; "rows × cols / FORMAT"; derived block (parent chips + collapsible derivation code); **Keys** block (PK/FK from `_erFkLinks`); columns table (Name | Type with PK/FK badges); Context notes textarea auto-saving via `PATCH /datasets/{id}/context` + **Generate notes** (C30 poll on `auto_notes_status`); data preview (~10 rows via `GET /datasets/{id}/preview`); actions **Clean / Re-derive / Delete**. The provenance readout (shown when `source_type` is present) covers both C36 ("from PostgreSQL: `<host>/<db>` · `<table>`") and C38 ("from Excel workbook: `sales.xlsx` · `2024`"); the **Re-sync** action keys on `origin === "connected"` only — never on `source_type` — so imported sheets (origin `uploaded`) show no re-sync.
- **Dataset strip:** horizontal chips (uploaded / derived + stale), uploaded first; click = `selectDataset`.

**Actions available:** select dataset, pan/zoom/fit the diagram, edit/generate notes, clean, re-derive, delete, clear database.

## Modals

All `.modal-overlay`, backdrop + Escape close, focus first element: `memory-modal`, `clean-modal`, `clear-sessions-modal`, `del-sel-sessions-modal`, `clear-all-datasets-modal`, `del-sel-modal`, `clear-db-modal`.

## Error States

- **Network / 5xx:** inline error banner in the relevant card ("is the server running?" for network failures); the conversation answer area shows the error, never a blank turn.
- **409 duplicate upload:** inline "Use existing / Upload anyway" resolver.
- **Loading:** Ask button shows a spinner and disables; the progress row shows elapsed time + Step N/M; "Checking…" during the clarification pre-flight.
- **Failed run:** the turn renders the run's `error_message`; a force-finalized run shows the **Best effort** badge instead of an error.
- **Stub mode:** the persistent yellow banner signals that answers are canned, not real.

## Accessibility

`role="log"` + `aria-live` on the thread; `role="list"`/`listitem`; `aria-label` on icon buttons; `aria-modal` + `aria-labelledby` on modals; `role="progressbar"` + `aria-valuenow` on the progress bar; a hidden `#aria-live` region + `announce()` helper; `type="button"` on every non-submit button.

## Phase Mapping (real vs labelled stub)

| Surface | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---------|---------|---------|---------|---------|
| Two-tab shell + header + stub banner | stub shell (real banner ok) | real | real | real |
| Upload card | labelled stub | **real** | real | real |
| Tables/datasets card | labelled stub | **real** (list + delete) | real | real (+derived/stale) |
| Conversation ask/answer/steps/tokens | labelled stub | **real** (single dataset) | real (multi-turn) | real (+charts) |
| Sessions sidebar | labelled stub | labelled stub | **real** | real |
| Clarification + suggestions | labelled stub | labelled stub | **real** | real |
| Token widget + C29 budget bar | labelled stub | partial (last/today) | real | real |
| Inline charts | labelled stub | labelled stub | labelled stub | **real** |
| Database tab (ER diagram, description) | labelled stub | labelled stub | labelled stub | **real** |
| Clean / Re-derive / Generate notes | labelled stub | labelled stub | labelled stub | **real** |
| Theme toggle (C34; accent/density are fixed, not live controls) | n/a (not built yet) | n/a | n/a | n/a — ships fully real in **Phase 7**, no stub stage |

A labelled stub renders the intended layout with a visible "coming in a later phase" tag so it is never mistaken for a bug. Phase 7 (theming, C34) is the one exception to the phased stub-to-real pattern above: it has no earlier phases to appear in, and ships fully functional the moment it lands — see [capabilities/theming.md](capabilities/theming.md) and `spec/roadmap.md` → Phase 7.
