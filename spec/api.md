# API

---

## API Style

REST over HTTP, served single-origin by FastAPI on port 8001. The built Next.js app is mounted at `/app`; API routes are at the root. **Success envelope:** `{"data": ..., "error": null}` via `ok(data)`. **Error envelope:** HTTP 4xx/5xx with `{"detail": {"code": ..., "message": ...}}` via `api_error(code, message, status_code)`. No authentication (single local user).

> Routers live in `src/api/` — one module per resource, registered in `create_app()`. The boilerplate `/runs` POST/GET stays unless it conflicts; the canonical analysis route is `/ask`. `GET /runs/current` is ADDED to `runs.py`.

## Endpoints / Commands

### `GET /health`
Returns `ok({status:"ok", provider:"<gemini|openrouter|stub|anthropic>", model:"<active-model-id>"})`. The `provider` field drives the UI stub banner; `model` is the model id the active provider will actually call (resolved via `LLMClient`) and drives the header "Live · &lt;model&gt;" badge. A provider-init failure falls back to `provider:"stub"` with `model:""`. Always 200.

### `GET /` and `/app`
The single-origin Next.js UI (static mount). Server starts API-only if `frontend/out/` is absent.

### `POST /upload`
Multipart `file`; form `context?`, `notes_file?`; query `force=false`. Parses (pandas), computes sha256, duplicate-checks (C10), saves CSV + Parquet, creates a `datasets` row, triggers async C30 notes. Accepts `.csv/.tsv/.txt/.json/.xlsx/.xls`. Returns `{dataset_id, filename, format, row_count, col_count, columns, context, auto_notes_status}`.

> **Notes truncation:** when `notes_file` is supplied its decoded text is **silently truncated to 4000 characters** before being stored as `context` — no error is returned for oversized notes files. This differs from `PATCH /datasets/{id}/context`, which rejects values exceeding 4000 chars with `400 context_too_long`. The plain `context` form field is stored as-is (no server-side truncation at upload).

> **Multi-sheet Excel workbooks (C38, Phase 12):** an `.xlsx`/`.xls` file whose workbook contains **≥ 2 non-empty sheets** does NOT register a dataset on this call. Instead the workbook's raw bytes are stashed server-side (in-memory, 15-min TTL, ≤4 staged workbooks, oldest evicted) and the response is the **inspect variant** below — the client then imports chosen sheets via `POST /upload/sheets`. No C10 dedup runs on this branch (nothing is persisted; re-dropping the same workbook to fetch another sheet must never 409) and `force` is ignored. A workbook with exactly **one** non-empty sheet keeps today's EXACT one-shot behavior above (no `type` key, filename unchanged, whole-file raw-bytes hash, upload-time dedup); zero non-empty sheets → 400 `empty_file`. Full rules in `spec/capabilities/multi-sheet-excel.md`.
>
> ```json
> {"type": "multi_sheet", "staging_token": "6f2c…", "filename": "sales.xlsx",
>  "sheets": [
>    {"sheet_name": "2023", "row_count": 812, "col_count": 9, "empty": false},
>    {"sheet_name": "2024", "row_count": 1043, "col_count": 9, "empty": false},
>    {"sheet_name": "Scratch", "row_count": 0, "col_count": 0, "empty": true}
>  ],
>  "context": null, "expires_in_seconds": 900}
> ```
>
> Sheets are listed in workbook order; empty sheets (0 rows or 0 cols) are included with `empty: true` so the picker can render them disabled. `context` echoes the C16-resolved workbook-level notes (notes_file wins, 4000-char truncation) that imported sheets will inherit. The single-sheet response is distinguished by the ABSENCE of a `type` key — its shape is byte-identical to the pre-C38 contract.

| Status | Condition |
|--------|-----------|
| 409 | `duplicate_dataset` (with `match_type` + `existing_*`); resolvable with `force=true` — single-sheet path only (the multi-sheet inspect never 409s) |
| 400 | bad extension / unparseable / empty file (incl. an all-empty-sheets workbook) |
| 500 | `write_failed` — disk write OR `session.commit()` failure (the row is rolled back; never a phantom `ok` for an unpersisted dataset) |

### `POST /upload/sheets`
C38 (Phase 12) — import chosen sheets from a staged multi-sheet workbook (the second step after a `type:"multi_sheet"` inspect response). Served by a NEW `src/api/upload_sheets.py` router (also home of the in-memory staging store), registered in `create_app()`. JSON body:

```json
{"staging_token": "6f2c…",
 "sheets": [
   {"sheet_name": "2023"},
   {"sheet_name": "2024", "context": "optional per-sheet notes override"}
 ],
 "force": false}
```

Re-parses ONLY the requested sheets from the stashed bytes (`.xls` via `engine="xlrd"`, D13 parity), and registers **each sheet independently** (C36's per-item precedent — one sheet's failure never aborts the others) as its own `datasets` row: `filename` = `` `{workbook} — {sheet_name}` ``, `format="excel"`, `origin="uploaded"`, per-sheet `content_hash` (sha256 of the sheet's canonical CSV serialization — NOT the workbook bytes, so sibling sheets never dedup-block each other), context = per-sheet override or the inherited workbook-level context, provenance `source_type="excel"` / `source_uri_display=<workbook filename>` / `source_table_name=<sheet name>` (`source_uri_raw` stays NULL), `auto_notes_status="pending"` + an async C30 notes job per sheet. CSV + Parquet written per sheet as usual. The staging token is NOT consumed (more sheets can be imported until TTL expiry). Returns 200 even if every sheet failed:

```json
{"filename": "sales.xlsx",
 "results": [
   {"sheet_name": "2023", "status": "ok",
    "dataset": {"dataset_id": "…", "filename": "sales.xlsx — 2023", "format": "excel",
                "row_count": 812, "col_count": 9, "columns": ["…"],
                "context": null, "auto_notes_status": "pending"}},
   {"sheet_name": "2024", "status": "duplicate", "match_type": "content",
    "existing_dataset_id": "…", "existing_filename": "sales.xlsx — 2024",
    "message": "This sheet was already imported. Re-import with force=true to keep both."},
   {"sheet_name": "Scratch", "status": "error", "message": "Sheet is empty."}
 ]}
```

Per-sheet `status`: `ok` (with `dataset` in the single-upload response shape) | `duplicate` (C10 fields — `match_type` `content`/`content_and_name`/`name`, `existing_dataset_id`, `existing_filename` — as a per-sheet result, not an HTTP 409; the UI shows the same inline "Use existing / Upload anyway" resolver, retrying that sheet with `force:true`) | `error` (empty sheet, unknown sheet name, parse/disk failure, or a per-sheet `session.commit()` failure — that sheet is rolled back and never poisons its siblings — `message` only).

| Status | Condition |
|--------|-----------|
| 404 | `staging_expired` — unknown or expired `staging_token` (re-drop the file) |
| 400 | `empty_selection` — missing/empty `sheets` list |

### `GET /datasets`
List datasets incl. `origin`, `stale`, `derived_*`, `derivation_description`. Always 200.

### `GET /datasets/{id}`
Full metadata incl. `columns_schema[{name, dtype-alias}]` (alias table in `spec/data.md`), `context`, `derivation_code`, `auto_notes_status`. **404** if missing.

### `GET /datasets/{id}/preview?rows=10`
`{columns, rows}` first N rows (clamp 1..50); per-cell formatting (floats round 4, whole floats → int, NaN → null). **404** missing / **500** read error.

### `GET /datasets/{id}/sessions`
Sessions scoped to that dataset. **404** missing.

### `DELETE /datasets/{id}`
Cascade delete (+ recursive derived, C15). **404** missing / **409** `dataset_in_use`.

### `DELETE /datasets`
Delete all + cascade.

### `PATCH /datasets/{id}/context`
Body `{context}` (≤4000). **400** `context_too_long` / **404** missing.

> Sending `{"context": ""}` or `{"context": null}` clears the field to `null` in the DB; callers reading back the dataset will receive `context: null`, not `""`.

### `POST /datasets/{id}/describe`
C30 trigger: set `auto_notes_status=pending`, generate notes async. **404** missing.

### `POST /datasets/{id}/re-derive`
C25 re-run `derivation_code` vs current parents; clears `stale`. **400** `not_derived` / **404** `parent_not_found` / **400** `re_derive_error`.

> On success, both `created_at` and `updated_at` on the derived dataset are reset to the current time. This is the mechanism that clears the staleness condition: a dataset is considered stale when `parent.updated_at > derived.created_at`, so resetting `created_at` after a successful re-derive makes the derived dataset current again.

### `POST /datasets/{id}/clean`
C24 NL cleaning PREVIEW: LLM generates pandas code, run on a copy, return `{code, before/after row+col counts, previews}`. **422** on clean exec error. **404** missing.

### `POST /datasets/{id}/clean/apply`
C24 apply code in place; rewrite CSV + Parquet, update counts. **422** exec error / **404** missing.

### `POST /ask`
Body `{question, session_id?, skip_clarification:false, fast_mode:false}`. Legacy `dataset_id?`/`dataset_ids?` are still accepted (API compat) but IGNORED — dataset selection is agent-driven, never client-scoped.
Dataset selection is AGENT-DRIVEN: every `/ask` hands the agent a metadata-only *catalog* of ALL workspace datasets and it picks (and lazily loads) whichever it needs. A `no_datasets` **400** is returned when the workspace is empty. Pre-flight C26 runs on the FIRST turn only (no `session_id`, unless `skip_clarification` OR `fast_mode`) → may return `{type:"clarification", clarification_question, suggested_questions, run_id, session_id}` (thin run, status `clarification`). Otherwise create the run (`status=running`), run the agent, return:
```json
{"type":"answer","run_id":"...","session_id":"...","dataset_ids":[...],
 "derived_dataset_ids":[...],"datasets_used":[...],"selector_reasoning":null,
 "answer_markdown":"...","answer_html":"...","charts":[...],
 "iteration_count":3,"tokens_input":1234,"tokens_output":567,"tokens_cached":812,
 "status":"completed",
 "is_best_effort":false,"steps":[...],"suggested_questions":[...],
 "prompt_breakdown":{...},"duration_ms":4210,"fast_mode":false}
```

> **`tokens_cached` field (C39, Phase 14):** an integer — how many of the run's cumulative `tokens_input` were served from the provider's prompt cache (Gemini `usage_metadata.cached_content_token_count`, accumulated at the same sites as `tokens_input`; the `generate_suggestions` call is deliberately excluded — documented scope bound in `spec/capabilities/prompt-cache-accounting.md`). Invariant: `0 ≤ tokens_cached ≤ tokens_input`. Cached tokens are a SUBSET of `tokens_input` counted at full value — they never reduce `tokens_input`, `prompt_breakdown`, or its exact-sum invariant; they only feed the frontend's discounted cost formula and the "X of Y from cache" line. `0` on a cold single-iteration run, on stub/anthropic/openrouter runs, and on all pre-Phase-14 rows — expected, never an error. NOT a key inside `prompt_breakdown` (payload-level only).

> **`fast_mode` field (C35, request + response):** a boolean, default `false`. When `true` on the request, the run applies a tighter per-request `max_iterations` (`5`, overriding the settings/DB value), SKIPS the C26 pre-flight clarification call outright (no clarifying-question roundtrip, regardless of first-turn status), SKIPS `generate_suggestions` (`suggested_questions` is always `[]`), truncates each `action_history` step's stored `result` to ~500 chars before it re-enters later prompts, adds a prompt-level brevity instruction (no hard output-token cap), and disables the forced-chart-retry guardrail (a chart is still rendered if the model produces one within the tighter budget, but no extra iteration is forced to get one). It never changes model/provider selection (that remains Settings-owned) and is never a settings/DB default applied to future requests — each `/ask` call states its own `fast_mode`. The response echoes the `fast_mode` value that was actually applied; the completed run's value is ALSO persisted on `query_runs.fast_mode` and returned per turn by `GET /sessions/{id}` (see the Turn payload note above), purely so the UI badge survives reload — see `spec/capabilities/fast-mode.md` → "Persistence Amendment".

> **`suggested_questions` on the clarification variant (C37, Phase 10):** the `type:"clarification"` payload carries `suggested_questions: string[]` — up to 3 refined candidate questions the user could tap instead of typing an answer, produced by the SAME single C26 pre-flight LLM call (no extra roundtrip; reply contract in `spec/capabilities/suggested-questions.md`). `[]` when the model offered none or its reply fell back to plain-text parsing — a parse failure NEVER blocks the clarification itself (the whole reply then becomes `clarification_question`, exactly the pre-C37 behavior). Live-only: not persisted, so a resumed clarification turn reports `suggested_questions: []` via `GET /sessions/{id}` (parity with answer-turn follow-up suggestions, which are also live-only today). Under Fast Mode the pre-flight is skipped entirely (C35), so this field never appears — no `type:"clarification"` response exists on a Fast Mode request.

> **`dataset_ids` vs `datasets_used`:** `dataset_ids` carries the raw **ids the agent actually LOADED** this run (used for session continuity and follow-up turns; empty if it loaded nothing). `datasets_used` carries the human-readable list of dataset **filenames** for display — each loaded id is mapped to its `DatasetRow.filename` (falling back to the id itself only if the row is missing). The UI renders `datasets_used` directly, so it must be names, never raw UUIDs. The two lists are positionally aligned.

> **`selector_reasoning`:** always `null` under agent-driven selection (there is no pre-flight selector). The key is retained on the payload for backward compatibility only.

> **`duration_ms`:** an integer — the wall-clock time of the whole agent run in milliseconds, measured in the `/ask` handler around `run_agent` (clarification + iterations + finalize). The UI shows it as the answer's response time ("took Xs"). Present on the answer payload only (a `clarification` short-circuit carries no `duration_ms`).

> **`charts` field:** a list of ECharts `option` JSON strings (`list[str]`). Each element is a `json.dumps`-serialised ECharts `option` dict produced by the sandbox `echart(kind, df, *, x, y, title, option)` helper — self-contained and passed directly to `echarts.init(...).setOption(JSON.parse(...))` by `ChartRender`. The list is empty (`[]`) when the agent produced no charts during the run. Charts are also persisted to `query_runs.charts_json` and surfaced via `GET /sessions/{id}` on each turn.

> **`prompt_breakdown` field (C29):** an object built by `_build_prompt_breakdown` (see `src/graph/runner.py`) describing the run's CUMULATIVE input composition. Keys: the five components `system_overhead`, `dataset_schemas`, `memory`, `history`, `action_history` (each an integer token count), plus `total_prompt` and `tokens_output`. Dataset notes are folded into `dataset_schemas` — there is no separate `dataset_notes` key. The five components are derived by accumulating per-bucket char counts across all ReAct iterations and **scaling** them to the real cumulative `tokens_input` (rounding residual absorbed into the largest bucket). **Invariant:** the five components sum **EXACTLY** to `total_prompt`, and `total_prompt` equals the run's REAL cumulative `tokens_input`. `tokens_output` carries the run's REAL cumulative output tokens. Fallback for a run that never planned (clarification short-circuit / cancelled-before-plan / zero total chars): the five buckets are `0`, `total_prompt` is the (likely `0`) `tokens_input`, and `tokens_output` is the cumulative output. See `spec/capabilities/context-window-display.md`.

| Status | Condition |
|--------|-----------|
| 404 | dataset or session not found |
| 400 | empty question / session mismatch / >20 turns / no datasets uploaded |

### `GET /suggestions/starters`
C37 (Phase 10) session-start starter questions — the "Try asking:" chips shown when the Analyse conversation is empty. Served by a NEW `src/api/suggestions.py` router (registered in `create_app()`). Takes NO parameters and requires NO session — the chips seed the composer before any session exists (a session is only created by the eventual `POST /ask`). Builds a **metadata-only** catalog of ALL workspace datasets (`columns_json` + compressed `context_facts` notes — no DataFrame/file reads, mirroring how `setup` builds the agent's catalog) and makes ONE `LLMClient` call (tag `<node:suggest>`, same JSON-array reply grammar as follow-up suggestions — see `spec/capabilities/suggested-questions.md`). Returns:

```json
{"questions": ["...", "...", "..."]}
```

`questions` is 0–3 strings. **Always 200, never a 5xx:** an empty workspace short-circuits to `{questions: []}` before any LLM call; an LLM error, an unparseable reply, or the offline stub provider (whose `<node:suggest>` branch returns `[]`) also yield `{questions: []}` — the UI hides the block on an empty list. Not Fast-Mode-gated (starters precede any query, and `fast_mode` is a per-`/ask` flag). The call belongs to no run, so its tokens are not attributed to `query_runs` / `GET /stats/daily` (documented, accepted gap).

### `GET /sessions`
All sessions, most-recently-updated first; each with `turn_count`, `first_question`. Always 200.

### `GET /sessions/{id}`
Session + `turns[]`. **404** missing.

> **Turn payload:** each turn (`_turn_payload`) carries `run_id`, `question`, `answer_markdown`, `answer_html`, `iteration_count`, `tokens_input`, `tokens_output`, `tokens_cached` (C39 — persisted, so the cache line survives reload/resume; `0` on pre-Phase-14 rows), `status`, `type` (`answer`|`clarification`), `clarification_question`, `steps`, `dataset_ids`, `suggested_questions` (always `[]` on resumed turns — suggestions are live-only, no persisted column; applies to answer follow-ups and C37 clarification candidates alike), `prompt_breakdown`, `charts`, **`fast_mode`** (bool — whether that specific completed run used Fast Mode; persisted on `query_runs.fast_mode` so it survives reload/resume, see `spec/capabilities/fast-mode.md` → "Persistence Amendment"), plus **`created_at`** (ISO string — when the turn was asked) and **`duration_ms`** (integer ms, derived from `updated_at − created_at` ≈ the run's lifespan, so resumed history shows a response time too; `null` when either timestamp is missing).

### `PATCH /sessions/{id}/name`
Rename. **404** missing.

### `DELETE /sessions/{id}`

Delete one session. **Does NOT cascade to `query_runs`** — run history is owned by the dataset, not the session; runs remain queryable after their session is deleted. Only the `conversation_sessions` row is removed. **404** if missing.

### `DELETE /sessions`

Body (optional): `{ "session_ids": ["id1", "id2", ...] }`

- With body: deletes only the listed sessions (skips any not found and any with a currently-running run). Returns `ok({ deleted: N })`.
- Without body: deletes all sessions. Returns `ok({ deleted_count: N })`.

**Does NOT cascade to `query_runs`** — runs remain queryable after their session is deleted.

### `GET /runs/current`
Most recent run `{run_id, status, iteration_count, max_iterations}` (status `idle` when none). Used for live progress polling (~1/s). Always 200.

### `GET /runs/{run_id}`

Returns the run row by id.
Response: `ok({ run_id, status, iteration_count, tokens_input, tokens_output, tokens_cached, answer, error_message, dataset_ids })`.
404 if not found.

### `POST /runs/{run_id}/cancel`
Cooperatively cancel an in-flight run — the UI **Stop** button. Flags the run so the ReAct graph wraps up at its next routing edge with NO further model calls (`force_finalize` short-circuits its synthesis call; suggestions are skipped). Returns `{run_id, cancelling: true}`. Idempotent / best-effort: a finished or unknown `run_id` is a harmless no-op (the flag clears when the run ends). Served on a different threadpool thread than the running request. Always 200.

> **Active runs routes:** `GET /runs/current`, `GET /runs/{run_id}`, and `POST /runs/{run_id}/cancel` are active. The boilerplate `POST /runs` route from the skeleton was removed — analysis runs are created exclusively via `POST /ask`.

### `GET /stats/daily`
`{date, model, tokens_input, tokens_output, tokens_cached, query_count, context_limit, last_prompt_tokens, last_tokens_input, last_tokens_output, last_tokens_cached}` aggregated over today's completed runs (server-local day); `context_limit` from a hard-coded model table (unknown → 128000). Always 200.

> **`last_prompt_tokens`:** an integer — the MOST RECENT completed run's input (`tokens_input`) tokens, i.e. the last query's prompt size (not the cumulative daily total). This is the per-request value the C29 context-window bar plots against `context_limit`; `0` when there are no completed runs today.

> **`last_tokens_input` / `last_tokens_output`:** integers — the latest completed run's input and output tokens. `last_tokens_input` is an explicit alias of `last_prompt_tokens`; `last_tokens_output` is the latest run's output tokens. The TokenWidget uses both to repopulate the "Last query (In / Out)" row after a reload/resume (when the live in-memory counts are gone). Each `0` when there are no completed runs today.

### `GET /memory` and `PATCH /memory`
Read / replace the global persistent memory text; PATCH triggers C31 compression. Memory is injected into every `plan_action` prompt as authoritative — `get_memory_block()` injects the compressed facts ONLY once they exist, falling back to the raw text only when there are no facts yet (never both, to avoid resending raw text plus a summary of it on every ReAct iteration). Always 200 on read; PATCH **400** if the body is invalid, or if `global_memory` exceeds 4000 characters (mirrors the dataset context-note cap).

### `GET /settings`
Returns the current runtime settings as key/value pairs. Always 200.

```json
{
  "data": {
    "llm_model": "gemini-3.1-flash-lite",
    "max_iterations": "10",
    "price_input_per_million": "0.25",
    "price_output_per_million": "1.50"
  },
  "error": null
}
```

> **Bare model IDs:** `llm_model` is stored and consumed as a BARE model id (e.g. `gemini-3.1-flash-lite`, `gemini-2.5-flash`) — no provider prefix. The same bare id is what the Settings dropdown writes, what the stats `_CONTEXT_LIMITS` table keys on, and what the provider passes to its SDK.

All four values are stored as strings in the `settings` table (or `null` if that key has never been set, in which case the server falls back to the env/default for that setting).

| Field | Type (stored) | Meaning |
|-------|---------------|---------|
| `llm_model` | string or null | LLM model override; `null` → use env/default |
| `max_iterations` | string or null | Max ReAct iterations override; `null` → use env/default |
| `price_input_per_million` | string or null | USD per 1 M input tokens for cost display; `null` → shown as N/A |
| `price_output_per_million` | string or null | USD per 1 M output tokens for cost display; `null` → shown as N/A |

### `PATCH /settings`

Updates one or more settings fields. Only fields present in the request body are written; omitted fields are left unchanged. Returns the full settings object (same shape as `GET /settings`) after applying the updates. Always 200.

**Request body** (all fields optional):

```json
{
  "llm_model": "gemini-2.5-flash-lite",
  "max_iterations": "5",
  "price_input_per_million": "0.10",
  "price_output_per_million": "0.40"
}
```

**Response:** same envelope as `GET /settings`, reflecting the post-update state.

### External Database Connectors (C36, Phase 9, BETA)

> Routes live in a NEW `src/api/connections.py` (not `datasets.py`) — a deliberate split: this surface deals with connector lifecycle + credential handling, a distinct concern from the existing dataset CRUD in `datasets.py`. All routes gated by `AGENT_ENABLE_DB_CONNECTORS` (default `false`) except `GET /connections/status`. A pulled table registers as an ordinary `datasets` row (`origin="connected"`) — see `spec/data.md` and `spec/capabilities/external-db-connectors.md` for the full mechanism and credential-hygiene rules.

### `GET /connections/status`
Returns `ok({enabled: <bool>})` — the current value of `AGENT_ENABLE_DB_CONNECTORS`. Always 200, never gated (the frontend needs this to decide whether to show the BETA affordance at all).

### `POST /connections/check`
Body `{type: "postgresql", uri: "postgresql://user:pass@host:5432/db"}`. Opens ONE connection, runs `connection_check()` (real connect + `SELECT 1`, 8s hard timeout) then `discover_tables()` + best-effort `discover_relationships()`, then closes the connection. **Nothing is persisted by this call.** Returns:
```json
{"tables": [{"table_name": "orders", "column_names": ["id","total"],
  "schema": [{"name":"id","dtype":"integer","nullable":false}, ...], "row_count": null}],
 "relationships": [{"from_table":"orders","from_column":"customer_id","to_table":"customers","to_column":"id"}]}
```
`row_count` is always `null` (introspection does not count rows). The response NEVER echoes the URI, raw or otherwise.

| Status | Condition |
|--------|-----------|
| 403 | `connectors_disabled` — `AGENT_ENABLE_DB_CONNECTORS` is `false` |
| 400 | `connection_failed` (credential-free message, e.g. `Could not connect to postgresql://host:5432/db: ...`) |
| 400 | `unsupported_type` — `type` is not `postgresql` |

### `POST /connections/import`
Body `{type: "postgresql", uri: "...", tables: [{table_name: "orders", alias?: "orders_snapshot", filter?: "created_at > '2026-01-01'"}, ...]}`. Re-validates via its own `connection_check()` → opens one connection → for EACH requested table independently: `pull_table(table_name, filter)` (bounded by a row cap, `LIMIT`-based — see the capability doc), writes `uploads/{new_id}.csv` + `.parquet`, creates a `datasets` row (`origin="connected"`, `source_type="postgresql"`, `source_uri_display=<credential-free>`, `source_table_name`, `source_uri_raw=<the raw URI, stored ONLY here>`). One table's failure does not abort the others. Returns:
```json
{"results": [
  {"table_name": "orders", "status": "ok", "dataset_id": "..."},
  {"table_name": "bad_view", "status": "error", "message": "permission denied for view bad_view"}
]}
```

| Status | Condition |
|--------|-----------|
| 403 | `connectors_disabled` |
| 400 | `connection_failed` (the initial re-validation connect itself failed — no tables attempted) |
| 400 | `unsupported_type` / empty `tables` list |

### `POST /connections/{dataset_id}/resync`
Manual re-sync (mirrors the Phase 4 `/datasets/{id}/re-derive` pattern — see `spec/capabilities/external-db-connectors.md`): re-opens a connection using the dataset's stored `source_uri_raw` + `source_type`, re-runs `pull_table(source_table_name)`, rewrites the CSV + Parquet files, recomputes `row_count`/`col_count`/`columns_json`/`content_hash`, and bumps `updated_at`. No automatic staleness flag exists for `origin="connected"` datasets — this is purely user-triggered. Returns the updated dataset via `_list_item` — the same **list-item** shape as an entry in `GET /datasets`' array (id, filename, format, row_count, col_count, columns, origin, context, auto_notes_status, stale, derived_from_run_id, derived_from_dataset_ids, derivation_description, source_type, source_uri_display, source_table_name, created_at, updated_at), NOT the fuller `GET /datasets/{id}` detail shape — it omits `columns_schema`, `content_hash`, `file_path`, `parquet_path`, `derivation_code`, `context_facts`. Same precedent as `POST /datasets/{id}/re-derive`, which also returns `_list_item`. `source_uri_raw` is never included. A caller needing the full detail shape after a resync should follow up with `GET /datasets/{id}`.

| Status | Condition |
|--------|-----------|
| 403 | `connectors_disabled` |
| 404 | dataset not found |
| 400 | `not_connected` — dataset's `origin` is not `connected` |
| 400 | `resync_error` — the pull failed (credential-free message) |

### Agent-built Dashboards (C40, Phase 15)

> Routes live in a NEW `src/api/dashboards.py` router, registered in `create_app()`. A dashboard belongs to exactly ONE dataset; the dashboard row stores the validated spec (incl. layout) and is re-computed against the dataset on every data fetch. Mechanism, fallback rules and the no-LLM-code decision: `spec/capabilities/dashboard-builder.md` + `spec/agent.md` → "Dashboard builder pipeline (C40)". All responses use the standard `ok()` / `api_error()` envelopes.

#### Dashboard spec v1 (the validated contract — `dashboards.spec_json`)

```json
{
  "version": 1,
  "title": "Sales overview",
  "description": "Revenue, units and top customers (optional, ≤300 chars)",
  "widgets": [
    {"id": "w1", "kind": "kpi", "title": "Total revenue",
     "layout": {"x": 0, "y": 0, "w": 3, "h": 2},
     "filters": [],
     "kpi": {"field": "revenue", "agg": "sum", "format": "currency"}},
    {"id": "w2", "kind": "chart", "title": "Revenue by region",
     "layout": {"x": 0, "y": 2, "w": 6, "h": 5},
     "chart": {"type": "bar", "x": "region",
               "y": {"field": "revenue", "agg": "sum"},
               "series_by": null, "time_grain": null, "sort": "y_desc", "limit": 10}},
    {"id": "w3", "kind": "chart", "title": "Monthly revenue",
     "layout": {"x": 6, "y": 2, "w": 6, "h": 5},
     "chart": {"type": "line", "x": "order_date",
               "y": {"field": "revenue", "agg": "sum"},
               "series_by": null, "time_grain": "month", "sort": "x_asc", "limit": 50}},
    {"id": "w4", "kind": "table", "title": "Top 10 customers by revenue",
     "layout": {"x": 0, "y": 7, "w": 12, "h": 6},
     "table": {"group_by": ["customer_id"],
               "aggs": [{"field": "revenue", "agg": "sum", "alias": "revenue"}],
               "sort_by": "revenue", "sort_dir": "desc", "limit": 10}}
  ]
}
```

| Element | Rule |
|---------|------|
| top level | `version` = `1`; `title` 1–80 chars; `description` ≤300 chars optional; `widgets` 1–12 items |
| widget common | `id` unique, `^[a-z][a-z0-9_-]{0,31}$` (server assigns `w1…wN` when missing/duplicate); `kind` ∈ `kpi`\|`chart`\|`table`; `title` 1–80 chars; exactly the ONE config block matching `kind` (`kpi`/`chart`/`table`), other blocks absent; `filters` ≤5 items (optional, default `[]`); `layout` `{x,y,w,h}` integers on a **12-column grid** |
| filter | `{field, op, value}`; `op` ∈ `eq ne gt gte lt lte in not_null`; `in` takes a list (≤50), `not_null` takes no `value`; `field` must exist; a filter whose `value` can't be coerced to the field's dtype is a validation error |
| `kpi` | `{field: string\|null, agg, format?, prefix?, suffix?}`; `agg` ∈ `sum mean median min max count nunique`; `field: null` allowed only with `agg:"count"` (row count); `format` ∈ `number\|integer\|currency\|percent` (default `number`); `prefix`/`suffix` ≤8 chars |
| `chart` | `{type, x, y?, series_by?, time_grain?, sort?, limit?, bins?}`; `type` ∈ `bar line area pie scatter histogram`; `x` = a field; `y` = `{field: string\|null, agg}` — required except for `histogram`; `agg` ∈ the KPI set, or `none` (scatter only; raw points, ≤2000 sampled evenly); `series_by` = optional categorical field (bar/line/area only; ≤8 distinct values kept, rest → "Other"); `time_grain` ∈ `day week month quarter year` — only when `x` is datetime (default chosen from the date span if omitted); `sort` ∈ `x_asc x_desc y_asc y_desc` (default `y_desc` for bar/pie, `x_asc` for line/area); `limit` 1–50 (default 20) = max categories/points after sort; `bins` 5–50 (default 20) for `histogram` (x numeric) |
| `table` | RAW mode: `{columns: [field…]}` (1–12 fields, first `limit` rows after `sort_by`); GROUPED mode: `{group_by: [field…] (1–3), aggs: [{field, agg, alias?}…] (1–6)}`; the modes are mutually exclusive; `sort_by` = a column/alias name (optional); `sort_dir` ∈ `asc\|desc` (default `desc` when grouped, `asc` raw); `limit` 1–50 (default 10) |
| field binding | a **real column name** of the dataset. Validation snaps a unique case/whitespace-insensitive match to the exact name; otherwise error `unknown_field`. dtype classes come from the `columns_schema` aliases (`integer/float` = numeric, `datetime`, `text/category/boolean` = categorical; object columns that parse as dates ≥95% are treated as `datetime`) |
| dtype rules | `sum mean median` → numeric only; `min max` → numeric or datetime; `count nunique` → any; `line/area` x → datetime (or numeric, ordered); `histogram` x → numeric; `pie` x → categorical; `scatter` x,y → numeric |
| `layout` | `x ≥ 0`, `1 ≤ w ≤ 12`, `x + w ≤ 12`, `1 ≤ h ≤ 12`, `y ≥ 0`; widgets must not overlap (rectangles `[x,x+w)×[y,y+h)` pairwise disjoint) |

**Validation error codes** (used in the repair prompt and in `generation.dropped_widgets[].reason`): `bad_json`, `bad_shape`, `unknown_kind`, `unknown_field`, `bad_agg`, `agg_dtype_mismatch`, `bad_chart_type`, `axis_dtype_mismatch`, `bad_filter`, `bad_table_mode`, `duplicate_id`, `too_many_widgets`, `out_of_range` (clamped where possible instead of rejected: `limit`, `bins`, `title` length).

**Default layout assignment** (backend `assign_layout`; the frontend `packLayout` MUST implement the identical algorithm — contract vector below): order widgets KPI → chart → table (stable within a kind); default sizes kpi `3×2`, chart `6×5`, table `12×6` (a widget keeps its `w`/`h` if it already has one); for each widget in order pick the smallest `y`, then smallest `x`, at which `[x,x+w)×[y,y+h)` is inside `0…12` columns and overlaps no already-placed widget. Contract vector: widgets `[kpi,kpi,kpi,kpi,chart,chart,table]` → `kpi(0,0) kpi(3,0) kpi(6,0) kpi(9,0) chart(0,2) chart(6,2) table(0,7)` (all as `w×h` above).

#### Dashboard record (the response object, `dashboard`)

```json
{"id": "…", "dataset_id": "…", "dataset_filename": "sales.csv",
 "title": "Sales overview", "command": "revenue by region and a monthly trend…",
 "spec": { "...Dashboard spec v1..." },
 "generation": {"used_fallback": false, "repaired": false, "supplemented": [],
                "dropped_widgets": [{"title": "Churn rate", "reason": "unknown_field: churn"}],
                "notes": [], "model": "gemini-3.1-flash-lite",
                "tokens_input": 2210, "tokens_output": 640, "duration_ms": 6120},
 "created_at": "…", "updated_at": "…"}
```

#### Widget data (the `data` object)

```json
{"dashboard_id": "…", "dataset_id": "…", "row_count": 1200, "computed_at": "…",
 "widgets": {
   "w1": {"kind": "kpi", "status": "ok", "label": "Total revenue", "value": 1234567.8,
          "formatted": "$1,234,568", "format": "currency", "caption": "sum of revenue"},
   "w2": {"kind": "chart", "status": "ok", "option": { "...ECharts option with a series key..." }},
   "w4": {"kind": "table", "status": "ok", "columns": ["customer_id","revenue"],
          "rows": [["C-1042", 83211.5]], "truncated": false},
   "w9": {"kind": "chart", "status": "error", "message": "Column 'discount' no longer exists."}}}
```

KPI `value` is `null` (with `status:"ok"`, `formatted:"—"`) when the filtered frame is empty. Table cells follow the preview formatting (floats rounded to 4 dp, whole floats → int, NaN → null). Chart `option` values go through the same JSON-safe coercion as the sandbox `echart` helper (NaN → null, Timestamp → ISO string).

### `POST /datasets/{id}/dashboards`
Body `{command, title?}`. Runs the dashboard-builder pipeline synchronously (profile → one LLM call → validate/repair → assign layout; deterministic fallback on any LLM/parse failure) and persists a new `dashboards` row. Returns `ok({dashboard, data})` — the record AND the computed widget data in one round trip (HTTP 200). A degraded run (`generation.used_fallback=true`) is still a 200. Typically 5–20 s with a live provider (one call, +1 on repair) — no progress polling; the UI shows a spinner. Never Fast-Mode-gated.

| Status | Condition |
|--------|-----------|
| 404 | `dataset_not_found` |
| 400 | `empty_command` (blank/whitespace) / `command_too_long` (>1000 chars) / `empty_dataset` (0 rows or 0 columns) |
| 500 | `dashboard_failed` (dataset file unreadable) / `write_failed` (`session.commit()` failure — rolled back, no phantom dashboard) |

### `GET /dashboards`
Optional query `dataset_id`. Summaries, most-recently-updated first: `[{id, dataset_id, dataset_filename, title, command, widget_count, used_fallback, created_at, updated_at}]`. Always 200 (empty list when none; entries whose dataset row is gone cannot exist — the cascade removes them).

### `GET /dashboards/{id}`
Returns `ok(dashboard)` (the record above). **404** `dashboard_not_found`.

### `GET /dashboards/{id}/data`
Recomputes every widget from the dataset's CURRENT file (safe pandas aggregation — `spec/agent.md`) and returns `ok(data)`. Per-widget failures are `status:"error"` entries, not HTTP errors. **404** `dashboard_not_found` / **404** `dataset_not_found` (defensive; cascade normally prevents it) / **500** `dashboard_failed` (dataset file unreadable).

### `PATCH /dashboards/{id}`
Body (all optional, at least one required): `{title?: string (1–80), layout?: [{id, x, y, w, h}, …]}`. `layout` must list EVERY widget id exactly once with integer coordinates satisfying the `layout` rules above (bounds + no overlap); it replaces `spec.widgets[].layout` atomically and bumps `updated_at`. Widget definitions (kind/bindings/filters) are NOT editable in this phase — only `title` and layout (field-drag reconfigure is Phase 16+). Returns `ok(dashboard)`.

| Status | Condition |
|--------|-----------|
| 404 | `dashboard_not_found` |
| 400 | `empty_patch` (no recognised field) / `invalid_title` / `invalid_layout` (unknown/missing/duplicate widget id, out of bounds, or overlap — stored layout unchanged) |
| 500 | `write_failed` |

### `DELETE /dashboards/{id}`
Deletes the dashboard row only (the dataset is untouched). Returns `ok({deleted: true})`. **404** `dashboard_not_found`. Deleting a dataset (`DELETE /datasets/{id}` / `DELETE /datasets`) also deletes its dashboards (C15 extension).

## Authentication

None — single local user. No API keys, sessions, or tokens for callers. Provider keys live in `.env` and never leave the server. Database connection URIs (C36) follow the same never-returned-by-any-API discipline as provider keys — see `spec/capabilities/external-db-connectors.md` → "Credential Hygiene".
