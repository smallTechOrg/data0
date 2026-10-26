# Data Model

---

## Storage Technology

SQLite via SQLAlchemy 2.0 declarative ORM (`DeclarativeBase`, `Mapped` columns), schema managed by Alembic. SQLite is the **production** database for this single-user local app. The four new models EXTEND the existing `Base` in `src/db/models.py` (alongside the boilerplate `RunRow`, which stays). `init_db()` builds all of `Base.metadata`, and the conftest `_isolated_db` fixture builds the same metadata into a temp SQLite copy — so the new models flow into tests automatically. UUID string PKs via the existing `_uuid()` helper; timestamps via `_now()` with `TIMESTAMP(timezone=True)`. JSON columns use SQLAlchemy `JSON`. Uploaded files live on disk at `uploads/{dataset_id}.csv` (+ `.parquet`), not in the DB.

> The 4 tables below are the source DATA MODEL verbatim. Relationships are **enforced in code, no FK constraints** (no `ForeignKey` in the migration), matching the skeleton's constraint-light style.

## Entities

### Entity: `datasets` (`DatasetRow`)

A registered data file (uploaded or derived) the agent can query.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key (`_uuid`) |
| filename | Text | yes | Original/display filename |
| file_path | Text | yes | On-disk CSV path (`uploads/{id}.csv`) |
| row_count | Integer | yes | Number of rows |
| col_count | Integer | yes | Number of columns |
| columns_json | JSON | yes | Column names + inferred dtypes |
| content_hash | Text | yes | sha256 of file bytes (duplicate detection, C10) |
| format | Text | yes | `csv` \| `tsv` \| `txt` \| `json` \| `excel` |
| context | Text | no | User/auto notes, ≤ 4000 chars (C12) |
| origin | Text | yes | `uploaded` \| `derived` \| `connected` (C36 — pulled from an external database, Phase 9) |
| derived_from_run_id | Text | no | The `query_runs.id` that produced this derived dataset |
| derived_from_dataset_ids | JSON | no | Parent dataset IDs (lineage, C25) |
| derivation_code | Text | no | The pandas code that produced it (re-derive, C25) |
| parquet_path | Text | no | On-disk Parquet path (`uploads/{id}.parquet`) |
| auto_notes_status | Text | no | `pending` \| `done` \| `failed` \| null (C30) |
| context_facts | JSON | no | Compressed ≤20 facts (C31) |
| source_type | Text | no | C36/C38 — source provenance discriminator: an external connector type (`postgresql`, C36) or `excel` (C38 — imported from a sheet of a multi-sheet workbook, Phase 12). `null` for plain uploads and `derived` origins |
| source_uri_display | Text | no | C36 — credential-free `DatasetURI.display()` rendering of the source connection (e.g. `postgresql://host:5432/mydb`); **C38 reuses it** as the source workbook's filename (e.g. `sales.xlsx`). Shown in the Tables/Database tabs as provenance; `null` unless `source_type` is set |
| source_table_name | Text | no | C36 — the external table this dataset was pulled from; **C38 reuses it** as the imported sheet's name. `null` unless `source_type` is set |
| source_uri_raw | Text | no | C36 — **secret-bearing**: the RAW connection URI including credentials, stored ONLY so a manual re-sync (`POST /connections/{id}/resync`) can reconnect. NEVER returned by any API response (every route builds its response dict field-by-field and omits this column), NEVER logged. `null` unless `origin="connected"` — C38 sheet imports never set it (nothing secret about a workbook; the workbook bytes are not retained, so no re-sync exists). See `spec/capabilities/external-db-connectors.md` → "Credential Hygiene". |
| created_at | TIMESTAMP(tz) | yes | `_now` default |
| updated_at | TIMESTAMP(tz) | yes | `_now` default + onupdate |

### Entity: `query_runs` (`QueryRunRow`)

One analysis run (one question → one answer), with its full step history.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| dataset_id | Text | no | Primary dataset (back-compat single ref) |
| session_id | Text | no | Owning conversation session (nullable for single-turn) |
| question | Text | yes | The user's question |
| answer | Text | no | Final Markdown answer |
| status | Text | yes | `pending` \| `running` \| `completed` \| `failed` \| `clarification` |
| error_message | Text | no | Failure reason, or `max_iterations` / `consecutive_errors` (informational on completed force-finalize) |
| action_history | JSON | no | `[{action, result, is_error, reasoning}]` (C23 steps; `reasoning` is the C33 per-step rationale, `""` when the model emitted none) |
| iteration_count | Integer | yes | Steps taken (live-polled, C22) |
| tokens_input | Integer | yes | Accumulated prompt tokens (C7) |
| tokens_output | Integer | yes | Accumulated completion tokens (C7) |
| tokens_cached | Integer | no | C39 — of `tokens_input`, how many were served from the provider's prompt cache (Gemini `cached_content_token_count`, accumulated like `tokens_input`). `nullable`, server-default `0` — pre-Phase-14 rows read as `0`. Invariant `0 ≤ tokens_cached ≤ tokens_input`; a SUBSET of `tokens_input` (never reduces it). Added by the Phase 14 Alembic migration. |
| prompt_breakdown | JSON | no | C29 token breakdown: five components scaled to sum to `total_prompt` (= cumulative `tokens_input`), plus `tokens_output` |
| charts_json | JSON | no | Persisted chart array from the run; reloaded as `charts[]` in `GET /sessions/{id}` turns so charts survive server restarts |
| dataset_ids_json | JSON | no | The datasets the agent actually LOADED this run (C14); scopes the C15 cascade |
| selector_reasoning | Text | no | Legacy C19 selector rationale; always NULL under agent-driven selection (column retained for compat) |
| fast_mode | Boolean | yes | C35 — whether this run used Fast Mode; set once at row creation, never updated. `nullable=False, default=False`. Returned per turn by `GET /sessions/{id}` so the "⚡ Fast Mode" badge survives reload (see `spec/capabilities/fast-mode.md` → "Persistence Amendment"). |
| created_at | TIMESTAMP(tz) | yes | `_now` default |
| updated_at | TIMESTAMP(tz) | yes | `_now` default + onupdate |

> **Note:** `suggested_questions` — both the post-answer follow-ups generated by `generate_suggestions` AND the C37 clarification candidates returned on a `type:"clarification"` response — are **ephemeral**: returned live in the `/ask` response but **not persisted** in `query_runs` (a clarification turn persists only the clarifying question, as `answer`). `GET /sessions/{id}` therefore returns `suggested_questions: []` per turn on reload. This is by design: suggestions are stateless, cheap to regenerate, and storing them would require a schema column not justified for the single-user local use case.

### Entity: `conversation_sessions` (`ConversationSessionRow`)

A named multi-turn conversation scoped to a set of datasets.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| dataset_id | Text | no | Primary dataset (back-compat single ref) |
| dataset_ids_json | JSON | no | Datasets the session is scoped to (C14) |
| name | Text | no | Display name (rename via PATCH) |
| created_at | TIMESTAMP(tz) | yes | `_now` default |
| updated_at | TIMESTAMP(tz) | yes | `_now` default + onupdate (most-recently-updated ordering) |

### Entity: `settings` (`SettingRow`)

Key/value app settings and persistent memory.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| key | Text | yes | Primary key |
| value | Text | no | Stored value (text or JSON-as-text) |
| updated_at | TIMESTAMP(tz) | yes | `_now` default + onupdate |

**Reserved keys:** `global_memory` (authoritative memory text, ≤ 4000 chars enforced at `PATCH /memory`; injected into every `plan_action` prompt via `get_memory_block()` — facts-only once `global_memory_facts` exist, raw-text fallback otherwise, never both), `global_memory_facts` (C31 compressed facts JSON, ≤ 20), `llm_model`, `max_iterations`.

### Entity: `dashboards` (`DashboardRow`)

C40 (Phase 15) — an agent-built dashboard over ONE dataset: the validated spec (widgets + field bindings + grid layout) plus how it was generated. Widget DATA is never stored — it is recomputed from the dataset file on each `GET /dashboards/{id}/data`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key (`_uuid`) |
| dataset_id | Text | yes | The dataset the dashboard is built on (→ `datasets.id`, enforced in code) |
| title | Text | yes | Display title (agent-proposed or user-supplied; editable via `PATCH`; ≤80 chars) |
| command | Text | yes | The user's natural-language command (≤1000 chars), kept for display/regeneration |
| spec_json | JSON | yes | The **Dashboard spec v1** object (`version`, `title`, `description?`, `widgets[]` each with its `layout {x,y,w,h}`) — schema in `spec/api.md` → "Dashboard spec v1". The single source of truth for layout; `PATCH` rewrites `widgets[].layout` here |
| generation_json | JSON | no | `{used_fallback, repaired, supplemented[], dropped_widgets[], notes[], model, tokens_input, tokens_output, duration_ms}` |
| tokens_input | Integer | yes | LLM prompt tokens spent building it (0 on a pure fallback); `server_default 0` |
| tokens_output | Integer | yes | LLM completion tokens spent building it; `server_default 0` |
| created_at | TIMESTAMP(tz) | yes | `_now` default |
| updated_at | TIMESTAMP(tz) | yes | `_now` default + onupdate (bumped by `PATCH`) |

**Migration:** one new Alembic revision creating the `dashboards` table (down-revision = the CURRENT head at build time — `f7a8b9c0d1e2` as of this spec; the builder must confirm by content with `uv run alembic heads`, since earlier roadmap text cites older heads). Index on `dataset_id`. No FK constraints (repo convention). Model added to `src/db/models.py` extending `Base`, so the `_isolated_db` fixture picks it up automatically.

### Relationships

Enforced in code only (no FK constraints):

- `dashboards.dataset_id` → `datasets.id` (cascade-deleted with the dataset, C15 extension)

- `query_runs.dataset_id` → `datasets.id`
- `query_runs.session_id` → `conversation_sessions.id`
- `conversation_sessions.dataset_id` → `datasets.id`
- `datasets.derived_from_run_id` → `query_runs.id`; `datasets.derived_from_dataset_ids[]` → `datasets.id` (lineage)

**Cascade delete (C15):** deleting a dataset cascades to its sessions, runs, **dashboards (C40)**, and on-disk files (CSV + Parquet) **and recursively deletes derived datasets whose `derived_from_dataset_ids` include it** (and their children, transitively). `DELETE /datasets` deletes all with the same cascade.

## dtype-alias table (for `columns_schema` in `GET /datasets/{id}`)

| pandas dtype | alias |
|--------------|-------|
| object / string | text |
| int* | integer |
| float* | float |
| datetime* | datetime |
| bool | boolean |
| timedelta | duration |
| category | category |

## Data Lifecycle

- **Created:** a `datasets` row on upload (origin=uploaded — incl. one row PER IMPORTED SHEET of a multi-sheet Excel workbook via `POST /upload/sheets`, C38: per-sheet `content_hash` over the sheet's canonical CSV serialization, filename `workbook.xlsx — Sheet`, provenance columns reused from C36, NO new columns/migration) or on `save_dataset` (origin=derived). A `dashboards` row per `POST /datasets/{id}/dashboards` (C40; updated by `PATCH` title/layout, deleted by `DELETE /dashboards/{id}` or its dataset's cascade). A `query_runs` row per `/ask` (or a thin row for a clarification). A `conversation_sessions` row when a session is started. `settings` rows on first write of a key.
- **Updated:** `datasets.context`/`context_facts`/`auto_notes_status` via describe/compress/PATCH; counts on clean/apply and re-derive; `query_runs.iteration_count` per step (live); `updated_at` on touch.
- **Deleted:** only on explicit user action (DELETE dataset/session/all). **No TTL / no auto-expiry** — datasets persist indefinitely.

## Sensitive Data

No auth, no PII handling by design — single local user. Uploaded data may contain anything the user uploads; it stays on local disk and SQLite and is sent to the configured LLM provider (Gemini/OpenRouter) only as needed for analysis (or never, in stub mode). API keys live in `.env` (git-ignored), never in the DB or logs. The `settings` table stores app config + user memory text, not secrets. **`datasets.source_uri_raw`** (C36, Phase 9) is the one exception to "the DB stores no secrets": it holds a database connection string with credentials, needed to support manual re-sync. It is never returned by any API response and never logged — see `spec/capabilities/external-db-connectors.md` → "Credential Hygiene".
