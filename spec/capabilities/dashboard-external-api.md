# Capability: External Dashboard Read API (C45)

## What It Does
External applications can fetch a saved dashboard's spec and its computed data (and a template's spec and required schema) through a small authenticated, read-only, versioned API.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| API key | string | `Authorization: Bearer <key>` or `X-API-Key` header | yes |
| id | path | `/external/v1/dashboards/{id}[...]`, `/external/v1/templates/{id}` | yes |
| filters | JSON | `?filters=` on the data route (C43 grammar) | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dashboard list | `[{id, title, summary, widget_count, dataset_filename, updated_at}]` | `GET /external/v1/dashboards` |
| dashboard spec | `{id, title, spec (v2), required_schema[], updated_at}` | `GET /external/v1/dashboards/{id}` |
| dashboard data | the same `data` object as `GET /dashboards/{id}/data` (incl. `insights`, `filter_options`) | `GET /external/v1/dashboards/{id}/data` |
| template | `{id, name, spec, required_schema[]}` | `GET /external/v1/templates/{id}` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| disk / SQLite | read dashboard, dataset frame | `404`/`500 dashboard_failed` as the internal routes |

## Business Rules
- **Read-only, GET only.** No mutation, no apply, no upload through this surface. `generation_json`, token counts, `command`, dataset file paths and every source/credential field are NEVER included.
- **Auth:** `AGENT_EXTERNAL_API_KEY` env var. Unset/empty ⇒ every `/external/v1/*` route returns `403 external_api_disabled` (secure by default). Wrong/missing key ⇒ `401 unauthorized` (generic message). Comparison via `hmac.compare_digest`; the key is never logged or echoed; log lines record only route + status + key-present boolean. This is deliberately separate from the unauthenticated internal API (single local user), which must NOT be network-exposed.
- Versioned prefix `/external/v1`; responses use the standard `ok()` envelope; the spec's `version` field (2) is the dashboard-spec version, independent of the URL version.
- `required_schema` lets a consuming app learn the shape up front (same structure as C44).
- Data is computed fresh on every call (a refreshed source is reflected); `ETag` = hash of (spec `updated_at`, dataset `updated_at`, filters) with `If-None-Match` → `304` so pollers are cheap.
- Rate limiting is out of scope (documented limitation); payload size is bounded by the engine's existing caps.

## Success Criteria
- [ ] Key unset → `403 external_api_disabled` on all four routes; wrong key → `401`; correct key via either header → 200.
- [ ] Spec route returns the v2 spec and `required_schema` equal to the C44 derivation; no field named `generation`, `tokens_*`, `command`, `source_uri_raw`, or any secret appears in any response (asserted by grepping bodies).
- [ ] Data route values equal the internal `/dashboards/{id}/data` for the same filters.
- [ ] Repeating a data call with the returned `ETag` and no change → `304`; after a dataset refresh → `200`.
- [ ] POST/PATCH/DELETE on `/external/v1/*` → `405`.

## Phase
Phase 18. Depends on C41 (spec v2) and C44 (`required_schema` derivation). See [dashboard-insights-priority.md](dashboard-insights-priority.md) for series assumptions.
