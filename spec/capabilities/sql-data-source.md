# Capability: SQL Database Data Source for Dashboards (C47)

## What It Does
The user supplies a READ-ONLY PostgreSQL connection string and either a table or a single SELECT query; the result is snapshotted into a normal dataset that drives dashboards and templates, and can be re-pulled on demand.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| type | `"postgresql"` (only engine, as C36) | `POST /data-sources/check`, `POST /data-sources` | yes |
| uri | connection string incl. credentials (secret) | same | yes (create); only if not stored (refresh) |
| table OR query | table name, or one `SELECT`/`WITH … SELECT` statement (≤10,000 chars) | same | exactly one |
| name, save_secret | as C46 | `POST /data-sources` | name yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| preview | `{columns[{name,dtype_class}], rows[≤20], row_count_estimate, truncated}` | `POST /data-sources/check` (nothing persisted) |
| source + dataset | `data_sources` row (`kind:"sql"`) + `datasets` row `origin="connected"`, `source_type="postgresql"`, `source_uri_display` (host/port/db only), `source_table_name` = table or `"query"` | `POST /data-sources` |
| refresh result | as C46 (`schema_diff`, `dashboards_affected`) | `POST /data-sources/{id}/refresh` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| PostgreSQL (`psycopg2`, via the C36 `PostgresConnector`) | `connection_check`; then `pull_query(sql)` in a READ ONLY transaction, `statement_timeout=30s`, wrapped `SELECT * FROM (<sql>) AS _q LIMIT 500001` | `400 connection_failed` / `400 query_rejected` / `400 query_failed` — all credential-free (URI + password scrubbed from driver text, as C36) |

## Business Rules
- **Reuse, not rewrite:** `PostgresConnector` (C36) gains `pull_query(sql)` beside `pull_table`; `DatasetURI`, the 8 s connect timeout, error sanitiser, `_MAX_PULL_ROWS=500,000` and the dataset-registration path are the C36 ones. Gated by the same `AGENT_ENABLE_DB_CONNECTORS` flag (off ⇒ `403 connectors_disabled`).
- **SELECT-only, defence in depth (`src/connectors/sql_guard.py`, pure):** (1) strip `--` and `/* */` comments and string literals for analysis; (2) reject if more than one statement (`;` outside literals); (3) first keyword must be `SELECT` or `WITH`; (4) reject any occurrence of `INSERT UPDATE DELETE MERGE DROP ALTER CREATE TRUNCATE GRANT REVOKE COPY CALL DO EXECUTE VACUUM REINDEX SET RESET LOCK NOTIFY LISTEN` and `INTO` after the select list (`SELECT … INTO`), plus `pg_sleep`, `pg_read_file`, `lo_import`, `dblink`; (5) the session is opened `readonly=True` (`SET TRANSACTION READ ONLY`) and always rolled back; (6) statement timeout and row cap above. A **table** pull builds `SELECT * FROM "<table>"` with the identifier validated against `information_schema` (no string interpolation of user text). The guard is a safety net; a dedicated read-only DB role is still the user's responsibility and the UI says so.
- **Credentials:** identical to C46 / series Assumed #5 — URI (with password) read only inside the connector; stored only Fernet-encrypted in `data_sources.secret_enc` when `AGENT_SECRET_KEY` is set (else session-only, `secret_required` on refresh); never in any response/log/dataset payload; the plaintext `datasets.source_uri_raw` column is NOT used by C47 (left null).
- **Snapshot semantics:** pulled once at create and on explicit refresh; no live query path, no scheduler, no agent SQL. Refresh overwrites the dataset files in place, recomputes counts/hash, returns the schema diff and affected dashboards (C44 binding statuses). Refresh failure leaves the previous snapshot intact.
- Same table + same DB reuse for templates: refresh the dataset, then dashboards recompute; or apply a template to a second source's dataset (C44).
- Truncated pulls (>500,000 rows) are flagged `truncated:true` on the dataset detail and the dashboard header shows "Snapshot truncated at 500,000 rows".
- Deleting the dataset cascades to its `data_sources` row.

## Success Criteria
- [ ] (offline, pure) `sql_guard` accepts `select a,b from t where c='x;y' -- note`, `WITH x AS (select 1) select * from x`; rejects `select 1; drop table t`, `delete from t`, `select * into new_t from t`, `select pg_sleep(10)`, `/* */ update t set a=1`, and an empty string, each with a stable code.
- [ ] (offline, fake psycopg2) `pull_query` issues the wrapped `LIMIT 500001` statement inside a read-only session and never commits; a driver error containing the password is scrubbed.
- [ ] (offline) `POST /data-sources` for a mocked source registers a dataset `origin="connected"`; no response/log/captured exception contains the password substring.
- [ ] (live, gated on `TEST_POSTGRES_URI` as C36) create from a real table and from a real `SELECT … GROUP BY` query; row count equals `SELECT count(*)`; a write attempt via the query field → `400 query_rejected` AND (using a role with write rights) the table is unchanged; refresh after inserting rows (via a separate admin connection) reflects them.
- [ ] A real-Gemini dashboard on the SQL-sourced dataset passes C40/C41 checks; its C44 template applies to a second source/table with the same columns with zero LLM calls.
- [ ] Refresh where a column was dropped from the query returns `needs_attention` for dashboards using it and keeps the old snapshot if the pull fails.
- [ ] UI: "Connect a SQL database" form (URI, Table|Query tabs, read-only reminder), Test → preview → Create; "Refresh data" on the dashboard header.

## Phase
Phase 19. Builds on [external-db-connectors.md](external-db-connectors.md) (C36) and shares the `data_sources` table, secret store and refresh route with [api-data-source.md](api-data-source.md) (C46). Series assumptions: [dashboard-insights-priority.md](dashboard-insights-priority.md).
