# Capability: REST API Data Source (C46)

## What It Does
The user points the app at a REST/JSON GET endpoint (optional header or bearer token); the JSON is flattened into a tabular snapshot registered as a normal dataset, can be re-fetched on demand, and can drive dashboards and templates exactly like an uploaded file.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| url | https?:// string | `POST /data-sources/check`, `POST /data-sources` | yes |
| headers | `{name: value}` (≤10; values are secrets) | same | no |
| bearer_token | string (secret; sent as `Authorization: Bearer`) | same | no |
| query_params | `{k: v}` (≤10) | same | no |
| records_path | dot path to the array, e.g. `data.items` | same | no (auto-detected) |
| name | string ≤80 | `POST /data-sources` | yes |
| save_secret | bool (default true; effective only if `AGENT_SECRET_KEY` set) | `POST /data-sources` | no |
| secret | `{headers?, bearer_token?}` | `POST /data-sources/{id}/refresh` (when not stored) | conditionally |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| preview | `{columns[{name,dtype_class}], rows[≤20], row_count, records_path_used, truncated}` | `POST /data-sources/check` (nothing persisted) |
| source + dataset | `data_sources` row (`kind:"api"`) and a `datasets` row `origin="api"`, `source_type="api"`, `source_uri_display` = scheme+host+path only (no query string, no credentials) | `POST /data-sources` |
| refresh result | updated dataset (in place), `schema_diff {added[], removed[], dtype_changed[]}`, `dashboards_affected[{id, binding_status: ok\|needs_attention, missing[]}]` | `POST /data-sources/{id}/refresh` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Remote REST API (`httpx`) | one GET (≤3 manual redirect hops), 15 s timeout, ≤25 MB streamed | `400 source_fetch_failed` (credential-free message: status class + host only) |
| DNS | resolve host for SSRF check | `400 url_blocked` |

## Business Rules
- **Gated** by `AGENT_ENABLE_API_SOURCES` (default `false`); off ⇒ `403 sources_disabled` (except `GET /data-sources/status`).
- **SSRF guards (all mandatory, `src/connectors/ssrf.py`):** scheme http/https only; reject userinfo in the URL; resolve all A/AAAA records and reject if ANY is loopback, private (RFC1918/ULA), link-local (incl. 169.254.169.254), multicast, reserved or unspecified; connect to the validated IP (Host header/SNI preserved) to defeat DNS rebinding; redirects are not auto-followed — each hop re-validated, ≤3; non-JSON `Content-Type` → `400 not_json`; body streamed and aborted at 25 MB (`413`-style `400 response_too_large`). `AGENT_ALLOW_PRIVATE_API_HOSTS=true` disables only the IP-class rejection (dev/tests), never the scheme/size/timeout rules.
- **Method is GET only**; no request body; custom headers cannot override `Host`, `Content-Length`, `Connection`.
- **Flattening (`flatten_json`, pure):** locate records: `records_path` if given; else root array of objects; else the first array-of-objects found breadth-first within depth 3; else a single root object → 1 row. `pandas.json_normalize(records, sep=".")`; nested arrays of scalars → compact JSON string; arrays of objects inside a record → JSON string (not exploded); column names deduped; ≤200 columns; rows capped at 100,000 (`truncated:true`). Dtypes inferred like uploads (numeric/datetime coercion ≥95%).
- **Registration reuses the upload dataset path:** writes `uploads/{id}.csv` + `.parquet`, `content_hash`, counts — identical downstream behaviour (Analyse tab, dashboards, templates). Dedup (C10) applies on first create only; refresh overwrites in place (like C36 resync).
- **Credential handling (see series Assumed #5):** secret parts (header values, bearer token) never appear in any response, log, error message, `source_uri_display`, or dataset payload. Persisted only encrypted (`data_sources.secret_enc`, Fernet, `AGENT_SECRET_KEY`); if the key is unset, nothing secret is stored and the source is flagged `secret_stored:false` — refresh must include `secret` in the body, otherwise `400 secret_required`. Non-secret config (url without query secrets, records_path, header NAMES) is stored in `config_json`. Query params are treated as secret if their name matches `key|token|secret|auth|password|sig` (stored in the encrypted blob, shown as `***`).
- **Refresh is on-demand only** (button / `POST …/refresh`); no scheduler. A failed refresh leaves the previous snapshot untouched and records `last_error` (credential-free). After a successful refresh dashboards on the dataset recompute on next open; ones whose required columns vanished are reported `needs_attention` (per-widget errors, C40 isolation) — see C44 binding report.
- Deleting the dataset cascades to its `data_sources` row (and secret blob). `DELETE /data-sources/{id}` removes the source+secret but KEEPS the dataset as a plain snapshot.

## Success Criteria
- [ ] (offline) `http://127.0.0.1`, `http://169.254.169.254/`, `http://[::1]`, a hostname resolving to 10.0.0.5, a redirect to a private IP, `file://`, and `http://user:pw@host` are each rejected `400 url_blocked`; with `AGENT_ALLOW_PRIVATE_API_HOSTS=true` loopback is allowed.
- [ ] (offline) `flatten_json` on `{"data":{"items":[{"id":1,"customer":{"name":"A"},"tags":["x","y"]}]}}` yields columns `id, customer.name, tags` (tags as JSON string) with auto-detected path `data.items`.
- [ ] (integration, local test server + `AGENT_ALLOW_PRIVATE_API_HOSTS`) a 600-record nested JSON endpoint with a bearer token registers a dataset with 600 rows; the token appears in NO response body, log capture, or `GET /datasets` payload (substring grep).
- [ ] Refresh after the test server's data changes updates row count/values in place and returns `schema_diff`; a refresh where a column was removed returns `needs_attention` for a dashboard using it.
- [ ] With `AGENT_SECRET_KEY` unset: `secret_stored:false`, refresh without `secret` → `400 secret_required`, with `secret` → 200.
- [ ] A >25 MB / >100,000-row / non-JSON / 500 / timeout response each yields a credential-free `400` and leaves the prior snapshot intact.
- [ ] A dashboard built (real Gemini) on the API-sourced dataset passes the C40/C41 checks; a C44 template from a file-built dashboard applies to it when the shape matches.
- [ ] UI: "Connect a REST API" form (URL, token, headers, records path) → Test → preview table → Create dataset; a "Refresh data" button on the dashboard header for sourced datasets.

## Phase
Phase 19. Reuses the C36 pattern ([external-db-connectors.md](external-db-connectors.md)): a snapshot-import connector, never a live query path. Series assumptions: [dashboard-insights-priority.md](dashboard-insights-priority.md).
