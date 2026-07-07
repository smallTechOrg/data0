# Capability: Multi-sheet Excel Import (C38)

## What It Does
When an uploaded `.xlsx`/`.xls` workbook contains more than one non-empty sheet, the user picks which sheet(s) to import via a checklist, and **each imported sheet is registered as its own `datasets` row** — from then on behaving EXACTLY like an uploaded CSV (same sandbox, same prompts, same C1–C37 capabilities). Today every tab except sheet 0 is silently dropped (`pd.read_excel` defaults to `sheet_name=0` in `src/api/upload.py::_parse_dataframe`); this capability makes the other tabs importable. This is a **data-loading mechanism, not a new agent action** — the ReAct loop makes ZERO new LLM calls, there are no graph changes and no new `AgentState` fields.

> **Approved core model (user decision, 2026-07-07):** sheet picker on multi-sheet workbooks + one-dataset-per-sheet registration; single-sheet workbooks keep today's exact one-shot behavior. Fixed — not re-derived here.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | multipart upload (`.xlsx`/`.xls`) | `POST /upload` (unchanged entry point) | yes |
| context / notes_file / force | as today (C16/C10) | `POST /upload` form/query | no |
| staging_token | string | `POST /upload/sheets` body | yes |
| sheets | list of `{sheet_name, context?}` | `POST /upload/sheets` body | yes (non-empty) |
| force | bool | `POST /upload/sheets` body | no (default false) |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| multi-sheet inspect response (`type:"multi_sheet"`, staging token, per-sheet name + row/col counts + `empty` flag) | JSON | `POST /upload` response (multi-sheet workbooks only) |
| one `datasets` row per imported sheet (`origin="uploaded"`, provenance columns set — see Business Rules) | DB rows | SQLite |
| CSV + Parquet per imported sheet | files | `uploads/{id}.csv` / `.parquet` |
| per-sheet import results (`ok` \| `duplicate` \| `error`) | JSON | `POST /upload/sheets` response |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| pandas + openpyxl | `pd.read_excel(BytesIO(raw), sheet_name=None)` — enumerate ALL sheets of an `.xlsx` as `{sheet_name: DataFrame}` | 400 `unparseable_file` |
| pandas + xlrd | same enumeration with `engine="xlrd"` for legacy `.xls` (D13 parity) | 400 `unparseable_file` |
| disk | write CSV + Parquet per imported sheet | per-sheet `status:"error"` (other sheets unaffected) |
| LLM (async, C30) | `trigger_describe_async(dataset_id)` per imported sheet (the C30 process-wide lock already serializes concurrent describes) | non-fatal; that sheet's `auto_notes_status=failed` |

## Business Rules

- **Picker trigger rule.** On an `.xlsx`/`.xls` upload, all sheets are enumerated (`sheet_name=None`). Count the **non-empty** sheets (a sheet is empty when it has 0 rows or 0 columns after parse):
  - **≥ 2 non-empty sheets** → nothing is persisted; `POST /upload` returns the `type:"multi_sheet"` inspect response (staging token + per-sheet metadata) and stashes the raw workbook bytes server-side. The C10 duplicate check does NOT run at this step (there is nothing to persist yet, and re-dropping the same workbook to import another sheet must never 409); the `force` query param is ignored on this branch.
  - **Exactly 1 non-empty sheet** → **today's EXACT single-shot behavior**: that sheet is parsed and registered immediately with the unchanged response shape (no `type` key), the unchanged `filename` (no sheet suffix), the unchanged whole-file raw-bytes `content_hash`, upload-time C10 dedup, C16 context resolution, and the C30 notes trigger. No picker, no contract change. *(Strict-improvement delta, documented: today pandas always reads sheet 0, so a workbook whose only data lives on a later tab currently 400s as empty — under this rule its single non-empty sheet imports directly.)*
  - **0 non-empty sheets** → 400 `empty_file` (matches today's empty-workbook outcome).
- **Server-side staging, not byte re-upload.** The inspect step stashes `(raw bytes, filename, ext, C16-resolved workbook context)` in an in-memory store in `src/api/upload_sheets.py`, keyed by a UUID `staging_token`. `POST /upload/sheets` re-parses **only the requested sheets** from the stashed bytes (`sheet_name=[...]`). The token is **not consumed** by a commit (the user may import more sheets from the same token until expiry). Entries expire after a **15-minute TTL** with an opportunistic sweep on each stash/lookup, and the store holds at most **4 workbooks** (oldest evicted on overflow). An unknown/expired token → 404 `staging_expired` ("re-drop the file"). The store is process-memory only — a server restart clears it; the user simply re-drops (single-user local app).
- **Dataset naming.** Each imported sheet's `filename` is `` `{workbook_filename} — {sheet_name}` `` (space–em-dash–space), e.g. `sales.xlsx — 2024`. This is the display name AND the C10 name-dedup key; the on-disk files remain `uploads/{id}.csv`/`.parquet` as for every dataset. Sibling sheets therefore never collide on name, and re-importing the same sheet later name-matches deterministically.
- **Dedup is per-sheet (C10 extension).** Each imported sheet's `content_hash` is the sha256 of the sheet's **canonical CSV serialization** (`df.to_csv(index=False).encode("utf-8")`), NOT the whole workbook's raw bytes. Consequences, all deliberate:
  - Importing sheet B is NEVER blocked by an earlier import of sheet A from the same workbook (different data → different hash; different name → different filename).
  - Re-importing the same sheet (even from a re-saved workbook whose raw bytes changed) → `duplicate` with `match_type:"content"` (or `content_and_name`); same `filename` with different data → `match_type:"name"`. Same fields as the C10 409 detail (`existing_dataset_id`, `existing_filename`), but delivered as a **per-sheet `status:"duplicate"` result** (the call itself stays 200 — C36's per-item-independence precedent), so the UI can show the existing inline "Use existing / Upload anyway" resolver per sheet.
  - `force:true` on `POST /upload/sheets` bypasses the check for all sheets in that call (per-sheet retry = re-call with just that sheet + `force:true`).
  - No cross-format dedup guarantee: a CSV upload hashes raw file bytes, so identical DATA uploaded as `.csv` vs imported as a sheet may not hash-match. Accepted; out of scope.
- **Per-sheet independence (C36 precedent).** Each requested sheet is parsed/persisted in its own try/except; one sheet's failure (empty, unknown name, parse or disk error) never aborts the others. `POST /upload/sheets` returns 200 with per-sheet `results` even if every sheet failed. Whole-call errors are only 404 `staging_expired` and 400 `empty_selection`.
- **Empty sheets.** Empty sheets ARE listed in the inspect response with `empty: true` (so the picker can render them disabled and the user understands why a tab they see in Excel is not importable — never silently missing). Requesting one at commit → per-sheet `status:"error"` ("Sheet is empty").
- **Context / notes propagation (C16 + C30).** The workbook-level `context`/`notes_file` supplied on the original `POST /upload` is resolved once (C16 precedence: notes_file wins, 4000-char truncation) and stashed; each imported sheet **inherits it** unless that sheet's commit entry carries its own `context` override (also ≤4000, same truncation). Each imported sheet gets `auto_notes_status="pending"` and its own async C30 notes job — one per dataset row, exactly as a multi-file upload batch does today.
- **Provenance — reuse the Phase 9 columns, NO migration.** Each imported sheet sets `source_type="excel"`, `source_uri_display=<workbook filename>`, `source_table_name=<sheet name>`; `source_uri_raw` stays NULL and `origin` stays `"uploaded"` (it IS an upload — there is no stored source to re-pull, so no resync exists for it). The existing C36 provenance readout renders it ("from Excel workbook: sales.xlsx · 2024"). **Any re-sync affordance keys on `origin === "connected"`, never on `source_type` presence** — the backend already enforces this (`/connections/{id}/resync` → 400 `not_connected`). Single-sheet direct imports set NONE of the provenance columns (exact-today contract).
- **Downstream equivalence.** After registration a sheet-dataset is indistinguishable from any uploaded dataset: agent catalog (C19), lazy load, dedup on later uploads, cascade delete (C15), cleaning (C24), notes (C30), sessions — no special-casing anywhere outside `src/api/upload.py`/`upload_sheets.py` and the Upload-card picker.
- **`.xls` legacy parity (D13).** The `.xls` branch performs the same enumeration with `engine="xlrd"` explicitly (pandas cannot auto-detect the engine from a BytesIO stream). Same picker rule, same commit path.

## Resolved Decisions

> **Assumed:** picker UI reuses the **C36 pick-tables checklist pattern** (checkbox + name + rows×cols + Import button), rendered inline inside the C17 staged-queue row — because sheets, like C36's discovered tables, are **server-enumerated sub-items of one source** (inspect → pick → import maps 1:1 onto C36's check → discover → import), whereas C13/C17 stages client-known files; the row lifecycle stays C17's, only the selection widget is C36's.
>
> **Assumed:** server-side staging token (in-memory, 15-min TTL, 4-workbook cap) over re-uploading the bytes on the commit call — avoids double-transferring up to 100 MB, keeps `POST /upload/sheets` a plain JSON endpoint, and is trivially offline-testable; restart-loss is acceptable for a single-user local app.
>
> **Assumed:** per-sheet content hash over canonical CSV bytes (not whole-file hash shared by siblings) — the only choice under which "re-import same sheet → duplicate" and "import a DIFFERENT sheet from the same workbook → allowed" are both true.
>
> **Assumed:** the picker triggers on ≥2 **non-empty** sheets (not ≥2 tabs) — Excel workbooks commonly carry empty default tabs; forcing a picker to choose the only sheet with data would be a pointless extra click and would break "single-sheet workbooks behave exactly like today" in spirit.
>
> **Assumed:** all non-empty sheets are **pre-checked** in the picker (unchecking is one click; the common intent when dropping a workbook is "import my data").
>
> **Assumed:** `source_type="excel"` as the provenance discriminator value (bare format label, consistent with `format="excel"`; the C36 column docs in `spec/data.md` are amended to cover this second use).

## Surfaces / files
- `src/api/upload.py` — the excel branch of `_parse_dataframe`/the upload handler gains sheet enumeration + the trigger rule; the row-registration logic is factored into a helper reused by the commit route. (backend slice)
- `src/api/upload_sheets.py` (NEW) — the in-memory staging store (stash/lookup/TTL sweep/cap) + `POST /upload/sheets`, registered in `create_app()` (`src/api/__init__.py`). (backend slice)
- `tests/unit/test_multi_sheet_upload.py` (NEW) — offline, in-memory openpyxl-built workbook fixtures (openpyxl and xlrd are already direct deps in `pyproject.toml`); the `.xls` enumeration branch is covered via a monkeypatched `pd.read_excel` because BIFF2 (the format `tests/unit/test_api_stub.py::_make_xls_bytes` can build without an xlwt dep) is structurally single-sheet. (backend slice)
- `frontend/src/lib/api.ts` — `MultiSheetUploadResponse` union variant on `api.upload`, `api.uploadSheets(...)` + result types. (frontend slice)
- `frontend/src/components/analyse/UploadCard.tsx` — the staged-row `pick_sheets` state + per-sheet result/duplicate handling. **(NOTE: the upload UI lives here, in `analyse/`, NOT `components/database/` — the roadmap backlog entry's indicative path was stale.)** (frontend slice)
- `frontend/src/components/analyse/SheetPickerRow.tsx` (NEW, optional split-out) — the checklist widget. (frontend slice)
- `frontend/src/components/database/TableDescriptionPanel.tsx` — generalize the C36 provenance line wording for `source_type="excel"` ("from Excel workbook: `<workbook>` · `<sheet>`"); Re-sync stays keyed on `origin === "connected"`. (frontend slice)

## Phase
Phase 12 (see `spec/roadmap.md` → "### Phase 12 — Multi-sheet Excel import (C38)").

## Success Criteria (all offline unless marked)
- [ ] (unit) Uploading an in-memory openpyxl workbook with 2 non-empty sheets + 1 empty sheet returns 200 `type:"multi_sheet"` with a `staging_token`, all 3 sheets listed in workbook order with correct row/col counts and `empty` flags — and persists NO `datasets` row and no files.
- [ ] (unit) Uploading a single-sheet `.xlsx` returns TODAY'S exact response shape (no `type` key, filename unchanged, whole-file raw-bytes hash — an identical re-upload 409s `duplicate_dataset` exactly as before).
- [ ] (unit) A workbook with one non-empty sheet among empty tabs imports that sheet directly (no picker); an all-empty workbook returns 400 `empty_file`.
- [ ] (unit) `POST /upload/sheets` with 2 selected sheets registers 2 `datasets` rows named `wb.xlsx — <sheet>`, each with its own CSV + Parquet on disk, per-sheet `content_hash`, `origin="uploaded"`, provenance columns (`source_type="excel"`, `source_uri_display`, `source_table_name`) set, `source_uri_raw` NULL, inherited workbook context (and a per-sheet `context` override where supplied), and `auto_notes_status="pending"`.
- [ ] (unit) Re-committing an already-imported sheet returns per-sheet `status:"duplicate"` with `match_type`/`existing_dataset_id`; committing a DIFFERENT sheet from the same token succeeds; `force:true` creates a second row.
- [ ] (unit) A requested empty sheet and an unknown sheet name each yield per-sheet `status:"error"` while sibling sheets in the same call still import; the call returns 200.
- [ ] (unit) An unknown/expired `staging_token` → 404 `staging_expired`; an empty `sheets` list → 400 `empty_selection`; a stashed entry past the 15-min TTL (clock monkeypatched) is swept; a 5th stashed workbook evicts the oldest.
- [ ] (unit) `.xls` parity: a single-sheet BIFF2 `.xls` imports exactly as today, and the `.xls` multi-sheet branch calls `pd.read_excel` with `engine="xlrd", sheet_name=None` and builds the picker from the returned dict (monkeypatched — see Surfaces note).
- [ ] (integration, real key, SCOPED) One multi-sheet workbook → import one sheet → one real `/ask` about that sheet returns a completed answer, proving an imported sheet behaves exactly like an uploaded CSV (`tests/integration/test_multi_sheet_real.py`).
- [ ] (manual) Dropping a multi-sheet workbook shows the picker with per-sheet counts and disabled empty sheets; single-sheet workbooks import directly with no picker; each imported sheet appears under Tables as its own dataset with an Excel provenance line and NO re-sync action.

## Out of Scope (non-goals)
- No new LLM calls, no graph/`AgentState`/prompt changes — pure data loading.
- No DB migration — provenance reuses the existing Phase 9 columns.
- No workbook re-sync (the workbook bytes are not retained past the staging TTL; `origin` stays `uploaded`).
- No cross-format dedup (CSV-vs-sheet of identical data may not hash-match).
- No "already imported" annotation in the picker (dedup surfaces at commit via the per-sheet `duplicate` status).
- No merged-cell/formula/styling fidelity beyond what `pd.read_excel` already does today.
