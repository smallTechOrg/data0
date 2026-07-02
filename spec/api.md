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

| Status | Condition |
|--------|-----------|
| 409 | `duplicate_dataset` (with `match_type` + `existing_*`); resolvable with `force=true` |
| 400 | bad extension / unparseable / empty file |
| 500 | disk write failure |

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
Dataset selection is AGENT-DRIVEN: every `/ask` hands the agent a metadata-only *catalog* of ALL workspace datasets and it picks (and lazily loads) whichever it needs. A `no_datasets` **400** is returned when the workspace is empty. Pre-flight C26 runs on the FIRST turn only (no `session_id`, unless `skip_clarification` OR `fast_mode`) → may return `{type:"clarification", clarification_question, run_id, session_id}` (thin run, status `clarification`). Otherwise create the run (`status=running`), run the agent, return:
```json
{"type":"answer","run_id":"...","session_id":"...","dataset_ids":[...],
 "derived_dataset_ids":[...],"datasets_used":[...],"selector_reasoning":null,
 "answer_markdown":"...","answer_html":"...","charts":[...],
 "iteration_count":3,"tokens_input":1234,"tokens_output":567,"status":"completed",
 "is_best_effort":false,"steps":[...],"suggested_questions":[...],
 "prompt_breakdown":{...},"duration_ms":4210,"fast_mode":false}
```

> **`fast_mode` field (C35, request + response):** a boolean, default `false`. When `true` on the request, the run applies a tighter per-request `max_iterations` (`5`, overriding the settings/DB value), SKIPS the C26 pre-flight clarification call outright (no clarifying-question roundtrip, regardless of first-turn status), SKIPS `generate_suggestions` (`suggested_questions` is always `[]`), truncates each `action_history` step's stored `result` to ~500 chars before it re-enters later prompts, adds a prompt-level brevity instruction (no hard output-token cap), and disables the forced-chart-retry guardrail (a chart is still rendered if the model produces one within the tighter budget, but no extra iteration is forced to get one). It never changes model/provider selection (that remains Settings-owned) and is never a settings/DB default applied to future requests — each `/ask` call states its own `fast_mode`. The response echoes the `fast_mode` value that was actually applied; the completed run's value is ALSO persisted on `query_runs.fast_mode` and returned per turn by `GET /sessions/{id}` (see the Turn payload note above), purely so the UI badge survives reload — see `spec/capabilities/fast-mode.md` → "Persistence Amendment".

> **`dataset_ids` vs `datasets_used`:** `dataset_ids` carries the raw **ids the agent actually LOADED** this run (used for session continuity and follow-up turns; empty if it loaded nothing). `datasets_used` carries the human-readable list of dataset **filenames** for display — each loaded id is mapped to its `DatasetRow.filename` (falling back to the id itself only if the row is missing). The UI renders `datasets_used` directly, so it must be names, never raw UUIDs. The two lists are positionally aligned.

> **`selector_reasoning`:** always `null` under agent-driven selection (there is no pre-flight selector). The key is retained on the payload for backward compatibility only.

> **`duration_ms`:** an integer — the wall-clock time of the whole agent run in milliseconds, measured in the `/ask` handler around `run_agent` (clarification + iterations + finalize). The UI shows it as the answer's response time ("took Xs"). Present on the answer payload only (a `clarification` short-circuit carries no `duration_ms`).

> **`charts` field:** a list of ECharts `option` JSON strings (`list[str]`). Each element is a `json.dumps`-serialised ECharts `option` dict produced by the sandbox `echart(kind, df, *, x, y, title, option)` helper — self-contained and passed directly to `echarts.init(...).setOption(JSON.parse(...))` by `ChartRender`. The list is empty (`[]`) when the agent produced no charts during the run. Charts are also persisted to `query_runs.charts_json` and surfaced via `GET /sessions/{id}` on each turn.

> **`prompt_breakdown` field (C29):** an object built by `_build_prompt_breakdown` (see `src/graph/runner.py`) describing the run's CUMULATIVE input composition. Keys: the five components `system_overhead`, `dataset_schemas`, `memory`, `history`, `action_history` (each an integer token count), plus `total_prompt` and `tokens_output`. Dataset notes are folded into `dataset_schemas` — there is no separate `dataset_notes` key. The five components are derived by accumulating per-bucket char counts across all ReAct iterations and **scaling** them to the real cumulative `tokens_input` (rounding residual absorbed into the largest bucket). **Invariant:** the five components sum **EXACTLY** to `total_prompt`, and `total_prompt` equals the run's REAL cumulative `tokens_input`. `tokens_output` carries the run's REAL cumulative output tokens. Fallback for a run that never planned (clarification short-circuit / cancelled-before-plan / zero total chars): the five buckets are `0`, `total_prompt` is the (likely `0`) `tokens_input`, and `tokens_output` is the cumulative output. See `spec/capabilities/context-window-display.md`.

| Status | Condition |
|--------|-----------|
| 404 | dataset or session not found |
| 400 | empty question / session mismatch / >20 turns / no datasets uploaded |

### `GET /sessions`
All sessions, most-recently-updated first; each with `turn_count`, `first_question`. Always 200.

### `GET /sessions/{id}`
Session + `turns[]`. **404** missing.

> **Turn payload:** each turn (`_turn_payload`) carries `run_id`, `question`, `answer_markdown`, `answer_html`, `iteration_count`, `tokens_input`, `tokens_output`, `status`, `type` (`answer`|`clarification`), `clarification_question`, `steps`, `dataset_ids`, `suggested_questions`, `prompt_breakdown`, `charts`, **`fast_mode`** (bool — whether that specific completed run used Fast Mode; persisted on `query_runs.fast_mode` so it survives reload/resume, see `spec/capabilities/fast-mode.md` → "Persistence Amendment"), plus **`created_at`** (ISO string — when the turn was asked) and **`duration_ms`** (integer ms, derived from `updated_at − created_at` ≈ the run's lifespan, so resumed history shows a response time too; `null` when either timestamp is missing).

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
Response: `ok({ run_id, status, iteration_count, tokens_input, tokens_output, answer, error_message, dataset_ids })`.
404 if not found.

### `POST /runs/{run_id}/cancel`
Cooperatively cancel an in-flight run — the UI **Stop** button. Flags the run so the ReAct graph wraps up at its next routing edge with NO further model calls (`force_finalize` short-circuits its synthesis call; suggestions are skipped). Returns `{run_id, cancelling: true}`. Idempotent / best-effort: a finished or unknown `run_id` is a harmless no-op (the flag clears when the run ends). Served on a different threadpool thread than the running request. Always 200.

> **Active runs routes:** `GET /runs/current`, `GET /runs/{run_id}`, and `POST /runs/{run_id}/cancel` are active. The boilerplate `POST /runs` route from the skeleton was removed — analysis runs are created exclusively via `POST /ask`.

### `GET /stats/daily`
`{date, model, tokens_input, tokens_output, query_count, context_limit, last_prompt_tokens, last_tokens_input, last_tokens_output}` aggregated over today's completed runs (server-local day); `context_limit` from a hard-coded model table (unknown → 128000). Always 200.

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

## Authentication

None — single local user. No API keys, sessions, or tokens for callers. Provider keys live in `.env` and never leave the server. Database connection URIs (C36) follow the same never-returned-by-any-API discipline as provider keys — see `spec/capabilities/external-db-connectors.md` → "Credential Hygiene".
