# Capability: External Database Connectors (C36)

## What It Does
A pluggable connector seam lets the user register an **external database table as a dataset** by pulling a bounded snapshot into a pandas DataFrame ONCE, at connect/registration time. From then on the resulting dataset behaves EXACTLY like an uploaded file — same `datasets` row shape, same sandbox, same prompts, same C1–C35 capabilities. Only one external engine ships working in this phase: **PostgreSQL** (read-only, BETA/flag-gated). The agent never talks to the external database directly and never runs SQL — this is a one-time data-loading mechanism, not a new agent action.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| type | string | `POST /connections/check`, `POST /connections/import` body | yes (`"postgresql"` only, in this phase) |
| uri | string | `POST /connections/check`, `POST /connections/import` body | yes — a full connection string incl. credentials; read only at connect time, never stored outside the one `source_uri_raw` column |
| tables | list of `{table_name, alias?, filter?}` | `POST /connections/import` body | yes — the tables the user chose to import after `check` |
| dataset_id | string (path) | `POST /connections/{dataset_id}/resync` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| discovered tables + relationships | list | `POST /connections/check` response (credential-free) |
| new `datasets` row(s), `origin="connected"` | DB row(s) | `POST /connections/import` response, same shape as `_list_item` (`GET /datasets`) plus provenance fields |
| re-synced dataset | DB row (updated in place) | `POST /connections/{dataset_id}/resync` response |
| connectors-enabled flag | bool | `GET /connections/status` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| PostgreSQL (`psycopg2`) | `connection_check()` — real connect + `SELECT 1`, hard wall-clock timeout (8s, via a worker-thread `.result(timeout=...)` since `psycopg2`'s own `connect_timeout` does not cover every stall) | `DatasetConnectionError` → API `400 connection_failed`, message built from `DatasetURI.display()` only, password scrubbed from the driver's own error text too |
| PostgreSQL (`psycopg2`) | `discover_tables()` — `information_schema.tables`/`columns`, `public` schema, base tables only | same as above |
| PostgreSQL (`psycopg2`) | `discover_relationships()` — `information_schema` FK joins (nice-to-have) | swallowed → `[]` (never blocks import) |
| PostgreSQL (`psycopg2` + `pandas`) | `pull_table(table_name, filter=None)` — `pd.read_sql(query, conn)` on the SAME connection already opened for `discover_tables()`, bounded by a row cap | `DatasetConnectionError` for that ONE table only; other requested tables in the same `/connections/import` call still attempt independently (see Business Rules) |

## Business Rules

- **Snapshot-import, never live SQL.** A connector pulls data ONCE, at connect/registration time (`POST /connections/import`) or on an explicit manual re-sync (`POST /connections/{id}/resync`). There is no MCP exposure, no live `query` tool, no persistent connection the agent talks to mid-run, and no new agent/graph action — the ReAct loop is completely untouched by this capability. See `spec/roadmap.md` → "External database connectors" backlog entry for the full rationale (verbatim design decision, not re-derived here).
- **No DuckDB.** `duckdb` is not and must not become a dependency. `psycopg2` handles introspection; `pd.read_sql` on the connector's own open connection handles the pull.
- **The connector seam is a registry, not a type-switch.** `src/connectors/base.py` defines `DatasetConnector` (ABC) + `get_connector(server: dict) -> DatasetConnector` (dispatch on `type`). A new engine = one new subclass + one registry entry; callers never branch on connector type. Two entries are wired in this phase: `parquet` (internal, wraps the EXISTING upload-based dataset store — see the note below) and `postgresql` (external, BETA).
  - **`parquet` is a formality, not a new upload path.** `POST /upload` remains the ONLY way to create an internally-uploaded dataset; the `ParquetConnector` class exists purely so the seam is genuinely pluggable end-to-end (the internal store round-trips through the same abstraction an external engine does) and is exercised only by unit tests and the registry itself — it is never called from any new HTTP route.
- **`DatasetURI` is the only credential boundary.** `.raw()` (the full URI, incl. password) is read ONLY inside a connector's own connect/introspect/pull calls. Every other surface — API responses, stored DB columns other than the one raw-URI column, log lines, exception messages, frontend state — uses `.display()` (host/port/db, no credentials) exclusively. See "Credential Hygiene" below.
- **`connection_check()` runs before anything is persisted.** `POST /connections/check` calls `connection_check()` then `discover_tables()` (+ best-effort `discover_relationships()`) on ONE opened connection and returns immediately — nothing is written to the DB by this call. Only `POST /connections/import`, which re-validates via the same `connection_check()` → `discover_tables()` → `pull_table()` sequence on its own freshly-opened connection, persists rows.
- **Bounded snapshot pull.** `pull_table(table_name, filter=None)` issues `SELECT * FROM "<table>" [WHERE <filter>] LIMIT <row cap>` on the connector's open connection.
  > **Assumed:** the row cap is `500,000` rows (`_MAX_PULL_ROWS` in `src/connectors/postgres.py`), matching the spirit of this app's existing 100 MB file-size target (`spec/roadmap.md` → Key Constraints) without requiring a byte-accurate SQL-side size probe. A table with more rows than the cap is silently truncated to the first `LIMIT` rows returned by Postgres (no ORDER BY is imposed — "first" per the server's own scan order); the imported dataset's row/col counts reflect the truncated snapshot, same as any other dataset.
  > **Assumed:** `filter` (when supplied per-table in `POST /connections/import`) is a raw SQL boolean expression inserted directly into the `WHERE` clause, trusted the same way this whole app trusts its single local user — this is not a multi-tenant surface and no other endpoint in this API sanitizes user-supplied logic beyond what the DB itself enforces (read-only credentials are the user's own responsibility, same posture as pandas code the agent already executes unsandboxed against the user's own files).
- **How a pulled table becomes a dataset.** `POST /connections/import` reuses the EXISTING `datasets` model exactly like `POST /upload` does: writes `uploads/{new_id}.csv` + `.parquet`, computes `content_hash`, sets `row_count`/`col_count`/`columns_json`, and sets `origin="connected"` (a new third value alongside `uploaded`/`derived` — see `spec/data.md`) plus the new provenance columns (`source_type`, `source_uri_display`, `source_table_name`, `source_uri_raw`). From that point on the dataset is indistinguishable from an upload to the sandbox, the ReAct loop, the prompts, and every other capability (C1–C35) — no special-casing anywhere else in the codebase.
- **Each requested table is imported independently.** `POST /connections/import` accepts multiple `{table_name, alias?, filter?}` entries in one call; each is pulled and registered in its own try/except, so one table's pull failure (e.g. a permissions error on one view) does not abort the others. The response reports a per-table result (`{table_name, dataset_id, status:"ok"}` or `{table_name, status:"error", message}`).
- **Manual re-sync mirrors the Phase 4 `/re-derive` pattern, not a new mechanism (per the backlog design decision).** `POST /connections/{dataset_id}/resync` re-opens a connection with the dataset's stored `source_uri_raw` + `source_type`, re-runs `pull_table(source_table_name)`, and — exactly like `src/graph/derived.py`'s re-derive path — rewrites the CSV + Parquet files, recomputes `row_count`/`col_count`/`columns_json`/`content_hash`, and bumps `updated_at`. Unlike derived-dataset re-derive, a connected dataset has no automatic "stale" flag (there is no cheap local signal for "has the external table changed" the way a parent's `updated_at` gives derived datasets) — re-sync here is purely a manual, user-triggered action; there is no `stale` badge for `origin="connected"` datasets in this phase.
- **Deletion is unchanged.** `DELETE /datasets/{id}` already cascades correctly for any `origin` value (C15); a connected dataset's `source_uri_raw` is removed along with the row, and the on-disk CSV/Parquet files are removed the same as any other dataset. No connector-specific delete logic is added.
- **BETA / flag-gated.** The whole `/connections/*` surface is gated behind `AGENT_ENABLE_DB_CONNECTORS` (bool env var, default `false`). When disabled, every `/connections/*` route (except `GET /connections/status`, which always reports the flag) returns `403 connectors_disabled`. `GET /connections/status` lets the frontend hide/show the BETA affordance without guessing.
- **Explicitly out of scope for this phase (deferred backlog sub-items, not touched by the seam beyond what a generic registry entry naturally allows):** SQLite, MongoDB, Snowflake connectors. `_REGISTRY` in `src/connectors/base.py` contains ONLY `parquet` and `postgresql` (+ a `postgres` alias) — no stub entries, no partial classes for the deferred engines.

## Credential Hygiene (hard requirement — see `harness/rules/ai-agents.md` / secret hygiene)

- The raw connection URI (with password) is read in exactly two places: (1) inside a `PostgresConnector`'s own `connect()`/`pull_table()` calls, sourced from the request body at `POST /connections/check` / `POST /connections/import` time, or from the stored `source_uri_raw` column at `POST /connections/{id}/resync` time; (2) the one write of `source_uri_raw` itself, at import time.
- Every OTHER surface — `POST /connections/check` and `POST /connections/import` responses, `GET /datasets` / `GET /datasets/{id}` (provenance shows `source_uri_display` only, `source_uri_raw` is NEVER included in any dataset JSON payload), log lines (`observability.events` structlog calls), stored `DatasetConnectionError` messages, and every frontend surface (Database tab dataset card, the connect-a-database form's own error banner) — uses `DatasetURI.display()` exclusively.
- Driver-level exceptions are sanitized before they leave a connector: the raw URI and the raw password (if present) are string-replaced out of the exception text before it is wrapped in `DatasetConnectionError` (mirrors the reference implementation's `_sanitize()` helper).
- `source_uri_raw` is a plain `Text` column (this app has no per-field encryption anywhere and does not introduce one here — same posture as the rest of the local, single-user SQLite DB) but is excluded from every `SELECT`-shaped API response by construction (the route handlers build response dicts field-by-field; they never do `row.__dict__`/`vars(row)`), and is never logged.

## Surfaces / files
- `src/connectors/base.py` (new) — `DatasetConnector` ABC (`connect`/`close`/`connection_check`/`discover_tables`/`pull_table` abstract or default; `discover_relationships` defaults to `[]`), `DatasetConnectionError`, `_REGISTRY`, `get_connector(server: dict)`. (backend slice)
- `src/connectors/uri.py` (new) — `DatasetURI` (`.raw()`, `.display()`, `.scheme`/`.host`/`.port`/`.database` helpers). (backend slice)
- `src/connectors/parquet.py` (new) — `ParquetConnector` (internal, wraps the existing `uploads/` store; see Business Rules). (backend slice)
- `src/connectors/postgres.py` (new) — `PostgresConnector` (`connection_check`, `discover_tables`, `discover_relationships`, `pull_table`, the hard-timeout wrapper, the error-sanitizer). (backend slice)
- `src/api/connections.py` (new) — `GET /connections/status`, `POST /connections/check`, `POST /connections/import`, `POST /connections/{dataset_id}/resync`, registered in `create_app()`. (backend slice)
- `src/db/models.py` — `DatasetRow` gains `source_type`, `source_uri_display`, `source_table_name`, `source_uri_raw` (all nullable `Text`). (backend slice)
- `alembic/versions/d4e5f6a7b8c9_add_connector_fields_to_datasets.py` (new) — the migration. (backend slice)
- `src/config/settings.py` — `enable_db_connectors: bool` (`AGENT_ENABLE_DB_CONNECTORS`, default `False`). (backend slice)
- `pyproject.toml` — adds `psycopg2-binary`. (backend slice)
- `frontend/src/components/database/ConnectDatabaseCard.tsx` (new) — the BETA "Connect a database" form (type dropdown, URI field, Test connection, table checklist, Import). (frontend slice)
- `frontend/src/components/database/DatabaseTab.tsx` — renders `<ConnectDatabaseCard />` inside the existing `.left-column-stack` (below `TablesCard`), gated on `GET /connections/status`. (frontend slice)
- `frontend/src/lib/api.ts` — `api.connections.status()/check()/import()/resync()` + response types. (frontend slice)
- `frontend/src/components/database/TableDescriptionPanel.tsx` (or wherever a dataset's metadata is shown) — an added one-line provenance readout ("from PostgreSQL: `source_uri_display` · `source_table_name`") when `source_type` is present. (frontend slice)

## Phase
Phase 9 (see `spec/roadmap.md` → "### Phase 9 — External database connectors (PostgreSQL, BETA)").

## Success Criteria
- [ ] (unit, offline/mocked) `get_connector({"type": "postgresql", "uri": "..."})` returns a `PostgresConnector`; an unknown `type` raises `DatasetConnectionError`.
- [ ] (unit, offline/mocked) `PostgresConnector.connection_check()` against a mocked `psycopg2.connect` that hangs past the timeout raises `DatasetConnectionError` with a message containing no password / no raw URI.
- [ ] (unit, offline/mocked) `PostgresConnector.discover_tables()` against a fake cursor returns `[{table_name, column_names, schema, row_count}]` with nullability captured per column.
- [ ] (unit, offline/mocked) `PostgresConnector.pull_table("orders")` against a fake connection calls `pd.read_sql` with a query containing the row-cap `LIMIT` and returns a DataFrame.
- [ ] (unit, offline) `DatasetURI("postgresql://u:p@host:5432/db").display()` contains no password and no username; `.raw()` returns the original string unchanged.
- [ ] (unit, offline) `ParquetConnector.discover_tables()` / `.pull_table(...)` work against the existing `datasets` table with zero network/LLM calls.
- [ ] (unit, offline) `POST /connections/import` with two requested tables, one whose mocked pull raises, registers the successful one and reports the failed one in the response without a 500.
- [ ] (unit, offline) With `AGENT_ENABLE_DB_CONNECTORS` unset/false, `POST /connections/check` returns `403 connectors_disabled`; `GET /connections/status` still returns `200 {enabled: false}`.
- [ ] (unit, offline) No test in `tests/unit/test_connectors.py` / `tests/unit/test_connections_api.py` requires `AGENT_GEMINI_API_KEY` or a real Postgres server — all `psycopg2` calls are mocked/faked.
- [ ] (integration, optional, gated on `TEST_POSTGRES_URI`) Against a real Postgres instance: `connection_check()` succeeds, `discover_tables()` finds at least one table, `POST /connections/import` registers it as a real `datasets` row, and a subsequent `/ask` (real Gemini) answers a question about it exactly as it would for an uploaded CSV.
- [ ] (manual/BETA) With the flag on, the Database tab shows a "Connect a database (BETA)" affordance; entering a PostgreSQL URI and clicking Test Connection lists real tables; importing one makes it appear under Tables with a "from PostgreSQL: `<host>/<db>`" provenance label; asking a question about it in the Analyse tab works exactly like an uploaded file; clicking re-sync re-pulls it and updates row/col counts.
- [ ] No response payload anywhere (API JSON, log line, or frontend state) ever contains the raw connection URI or password — verified by grepping the response bodies / captured logs in the new tests for the URI's password substring.

## Out of Scope (non-goals)
- No live SQL querying / no agent SQL action — this is a one-time snapshot pull, never a mid-run tool.
- No DuckDB dependency.
- No SQLite, MongoDB, or Snowflake connectors (remain deferred backlog sub-items — see `spec/roadmap.md`).
- No automatic staleness detection for connected datasets (re-sync is manual-only, unlike derived-dataset staleness).
- No encryption of `source_uri_raw` at rest — same posture as the rest of this local, single-user SQLite DB.
- No write access to the external database — every connector method in this phase is read-only.
