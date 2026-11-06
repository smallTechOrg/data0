# Capability: Priority-ranked Dashboard Insights (C41)

> **Series anchor.** C41–C47 turn the Phase 15 dashboard (C40) into a "Power-BI-grade" builder: ranked insights (C41), widget editing/regenerate/rebinding (C42), dashboard filters (C43), reusable templates (C44), external read API (C45), REST API source (C46), SQL DB source (C47). This file also holds the consolidated **Assumed decisions** for the whole series (bottom). Power BI / Tableau export is explicitly OUT OF SCOPE for the series: both were researched and use proprietary, non-open file formats and ship their own agents, so reuse is delivered through this product's own templates (C44) and external read API (C45) instead.
>
> **What a dashboard looks like (series-wide definition).** One dashboard = ONE dataset + a **Dashboard spec v2** (`spec/api.md`): a title, a one-line `summary`, optional dashboard-level `filters` (C43), and 1–12 **widgets** (`kpi` | `chart` | `table`). Every widget carries a `priority` (global rank, 1 = most important), a one-line agent-written `description` (why it matters), and — for charts — a `chart_rationale` (why this chart type fits this data). Layout is a 12-column grid in reading order (priority 1 top-left). A "Key insights" headline row shows the top KPIs numbered 1..N. Data is never stored; it is recomputed from the dataset on every open.

## What It Does
The agent ranks every widget of a dashboard by importance and writes a short "why it matters" description per widget (and a chart-type justification per chart); the UI shows a numbered "Key insights" headline row and lays widgets out in priority reading order, and the user can reorder priority.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_id, command, title? | as C40 | `POST /datasets/{id}/dashboards` | yes |
| priority_order | `[widget_id, …]` — every widget id exactly once, most important first | `PATCH /dashboards/{id}` | no |
| rearrange | bool (default `true`) | `PATCH /dashboards/{id}` (with `priority_order`) | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| spec v2 | `spec.summary`, per-widget `priority` (int), `description` (≤200), `chart_rationale` (≤140, charts only), `description_source` (`agent`\|`auto`\|`user`) | `dashboards.spec_json`, `POST`/`GET` responses |
| insights | `data.insights = [{rank, widget_id, title, headline, why}]` — KPI widgets in priority order, `headline` = the formatted KPI value, `why` = the widget `description`; ≤6 entries; `rank` is the 1..N display position | `GET /dashboards/{id}/data` and the `POST` response |
| priority-ordered layout | each widget's `layout` | `spec_json` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| LLM via `LLMClient` | the SAME single C40 call (`<node:dashboard>`) — the prompt/reply grammar is extended with `priority`, `description`, `chart_rationale`, `summary`; no extra call | unusable/missing fields never fail the build: server fills them deterministically (below) |

## Business Rules
- **No new LLM call.** Ranking, descriptions and chart justification arrive in the one existing build call (≤1 repair, as C40). Reordering priority (`PATCH priority_order`) is pure server logic — no LLM.
- **Priority is a dense global rank 1..N** over all widgets, unique. The server normalises whatever the LLM returned: sort by given `priority` (missing/non-int/duplicate → keep reply order as tie-break), then renumber 1..N. User-supplied `priority_order` must list every widget id exactly once (else `400 invalid_priority`).
- **Deterministic fallbacks for the text fields** (so a fallback or partly-valid reply is still "pro"): `description` missing → auto caption from the spec (e.g. "Total of revenue across all 600 rows." / "revenue summed by region, top 10."), `description_source="auto"`; `chart_rationale` missing → rule-derived (below), `auto`. Fallback dashboards (C40) rank: Rows KPI last among KPIs, measure KPIs first, then charts, then table.
- **Chart-type selection rules** (single source of truth in `src/graph/dashboard_charts.py`, used by (a) the prompt guidance, (b) the validator's advisory/clamp, (c) the fallback generator, (d) C42's chart-suggestions): time x + measure → `line` (`area` if cumulative-looking/few series); categorical x ≤ 8 distinct + measure, parts-of-whole intent → `pie` else `bar`; categorical 9–50 distinct → `bar` (sorted, top-N `limit`); two numerics → `scatter`; single numeric distribution → `histogram`; series_by only on bar/line/area. **Hard clamps:** `pie` with >8 categories is converted to `bar` and a note recorded in `generation.notes`; `line/area` on a non-ordered x → `bar`. The LLM may deviate within the dtype-valid set; its `chart_rationale` is kept (advice, not a veto).
- **Headline row:** the top ≤4 KPIs by priority form the "Key insights" row (numbered 1..N by position); further KPIs render in the normal flow. A dashboard always has ≥1 KPI (C40 composition guarantee), so the row is never empty.
- **Reading-order layout (`assign_layout` v2):** order = KPIs by priority asc, then charts+tables merged by priority asc; same first-fit algorithm/sizes as C40 (contract vectors in `spec/api.md`). Layout is auto-assigned on create/regenerate and on `PATCH priority_order` with `rearrange:true`; drag-rearrangement (C40) is otherwise preserved. `rearrange:false` changes ranks only.
- **v1 → v2 upgrade is lazy and lossless:** a stored v1 spec is read as v2 with `priority` = row-major reading order, `description` = auto caption, `summary` = null; it is rewritten as v2 on its next write. No data migration.
- Text fields are plain text (React-escaped; never rendered as HTML); LLM text is truncated, not rejected, when over length.
- **Agent text never states a finding.** The agent writes `summary` and `description` from the data profile, before any widget is computed, so they say what the reader will learn and why it matters, never a trend, ranking or comparison ("North leads", "revenue is growing"). Real values come only from the computed widgets (KPI `headline`, chart, table).

## Success Criteria
- [ ] Real Gemini build on a 600-row orders CSV returns every widget with a unique dense `priority` 1..N, a non-empty `description` ≤200 chars, every chart with a non-empty `chart_rationale`, `used_fallback=false`.
- [ ] A monthly-trend chart on a datetime x is `line` or `area`; no `pie` has >8 categories (unit-tested by feeding a reply with a 20-category pie → converted to `bar` + note).
- [ ] Reply with duplicate/missing/out-of-range priorities → normalised to dense unique 1..N in reply order (unit test).
- [ ] Reply lacking descriptions → `description_source="auto"` captions, non-empty; build still HTTP 200 (unit + stub-provider fallback).
- [ ] `assign_layout` v2 equals the contract vector in `spec/api.md`; the priority-1 KPI is at (0,0).
- [ ] `PATCH priority_order` with `rearrange:true` re-packs so widget order by (y,x) equals priority order (KPIs first); `rearrange:false` leaves layout byte-identical; incomplete/duplicate list → `400 invalid_priority`, stored spec unchanged.
- [ ] `data.insights` is ordered by priority, ≤6, KPI-only, and `headline` equals the full-data KPI value.
- [ ] A stored v1 dashboard opens as v2 (priorities by reading order) without error.
- [ ] UI: "Key insights" row shows numbered KPI cards with the why-line; each widget shows its description (and chart rationale under chart titles); a priority panel reorders ranks.

## Phase 16 additions (as built): AI workspace — domain, data insights, chat edit

Extends C41 beyond the original scope; code is the source (`src/graph/dashboard_insights.py`, `refine_dashboard`, `POST /dashboards/{id}/chat`). Contracts: `spec/api.md` (data fields + chat route), `spec/agent.md` (Phase 16 additions), `spec/ui.md` (three-column layout).

**Business rules**
- `domain` is detected from column names only (≥2 keyword matches, else `general`); a non-general hint is added to the build and refine prompts as `## Dataset type`; no data values are sent through it.
- `ai_insights` (≤8) and `overview` are deterministic and LLM-free, computed on the full dataset; text states only computed values, never causes — the no-stated-findings rule above holds.
- Chat edit costs 1 LLM call, is re-validated like a build, never accepts LLM layout, and on any unusable reply leaves the stored dashboard untouched (`changed:false`, HTTP 200).

**Success Criteria (additions)**
- [ ] `GET /dashboards/{id}/data` returns `domain`, `overview` and `ai_insights` (≤8); a sales-like column set yields `domain.key=="sales"`, and a set with <2 keyword matches yields `general` with `confidence` 0.
- [ ] `overview.rows`/`columns`/`missing_cells`/`duplicate_rows` equal the pandas values for the dataset; `completeness` = 100·(1 − missing/cells) to 1 dp.
- [ ] Every `ai_insights` text number can be reproduced from the dataframe (e.g. leader share and first→last % change); no insight contains a causal claim; a fixture with >5% missing in a column yields a `quality`/`warning` insight naming it.
- [ ] `POST /dashboards/{id}/chat` with a valid message returns `{reply, changed, dashboard, data}`; with `refine_dashboard` returning a spec, `changed:true`, the row's spec/title/`updated_at` are updated and layout is server-assigned.
- [ ] Chat with an unusable LLM reply (unparseable / zero valid widgets / LLM error) returns HTTP 200 `changed:false` and the stored spec is byte-identical.
- [ ] Chat errors: blank message → 400 `empty_message`; 1001 chars → 400 `message_too_long`; unknown dashboard → 404 `dashboard_not_found`; missing dataset → 404 `dataset_not_found`; unreadable file → 500 `dashboard_failed`.
- [ ] UI: AI workspace shows AI Insights and Chat & edit tabs; a changed chat reply updates the canvas without reload and shows "Dashboard updated"; the domain badge and record/column/completeness pills render in the canvas header.

## Assumed decisions (consolidated for C41–C47)
> **Assumed:** (1) **Chart rationale is a separate `chart_rationale` field** (displayed directly under the widget description, same text block) rather than folded into `description`, so the insight text stays about the data and the chart justification can be regenerated deterministically after a rebind without an LLM call.
> **Assumed:** (2) **Priority is global**; the headline-row numbers 1..N are display positions of the KPIs, not the global priority.
> **Assumed:** (3) **Phasing:** Phase 16 = C41; Phase 17 = C42 + C43; Phase 18 = C44 + C45; Phase 19 = C46 + C47. The "≥3 capabilities per phase" rule is waived by the explicit instruction to ship small independently testable phases (as Phase 15).
> **Assumed:** (4) **Sources:** files (C40) + REST/JSON API (GET only, optional header/bearer token, JSON flattened with `json_normalize`) + SQL DB via user-supplied READ-ONLY PostgreSQL connection string with a single `SELECT`/table. All sources are **snapshotted into a normal dataset**; dashboards stay bound to a dataset (no live query path). Other engines (MySQL, SQLite, Snowflake…) = one new connector class later (C36 registry). **No scheduled refresh** — refresh is on demand only.
> **Assumed:** (5) **Credentials are secrets.** Never logged, never in any API response, never in `GET /datasets`. Storage: a `data_sources.secret_enc` column encrypted with Fernet using `AGENT_SECRET_KEY` (new env var). If `AGENT_SECRET_KEY` is unset, secrets are **not persisted at all** — the user re-enters them per refresh (session-only). **Trade-off flagged:** this is stronger than C36's plaintext `source_uri_raw` precedent, but the key lives in `.env` on the same host, so it protects against DB-file leakage/backup exposure, not against host compromise. C36's existing plaintext column is untouched.
> **Assumed:** (6) **SSRF guards** on API URLs (http/https only; resolve host and reject loopback/private/link-local/metadata/multicast IPs; connect to the validated IP; redirects not auto-followed, ≤3 manual hops each re-validated; 15 s timeout; ≤25 MB body; ≤100,000 rows). `AGENT_ALLOW_PRIVATE_API_HOSTS=true` (default false) opts in to private hosts for local development/tests. **DB guards:** statement must be a single `SELECT`/`WITH…SELECT` (comments stripped, `;`-chaining and DML/DDL keywords rejected), run in a READ ONLY transaction with `statement_timeout` 30 s, wrapped in `LIMIT 500001` (cap 500,000 rows, same as C36); a read-only DB role remains the user's responsibility (defence in depth, not the only guard). Both connectors gated by the existing `AGENT_ENABLE_DB_CONNECTORS` flag family: DB source by it directly; API source by new `AGENT_ENABLE_API_SOURCES` (default `false`, BETA).
> **Assumed:** (7) **Template = spec + required-column schema with dtype classes.** "Apply to dataset" binds by exact → unique case/whitespace-insensitive match; near-matches are only **suggested** and applied after the user confirms a `mapping`; applying never calls the LLM; mismatch → `422 binding_mismatch` with a full report. dtype compatibility is by class (numeric / datetime / categorical), no silent coercion of text to numbers.
> **Assumed:** (8) **External read endpoints** live under `/external/v1/*`, GET-only, protected by `AGENT_EXTERNAL_API_KEY` (Bearer or `X-API-Key`; constant-time compare; unset ⇒ routes return `403 external_api_disabled`). The rest of the API stays unauthenticated (single local user) — the key guards only the surface meant to be exposed. No CORS added (server-to-server use); `AGENT_EXTERNAL_CORS_ORIGINS` optional allow-list.
> **Assumed:** (9) **Regenerate** defaults to `mode:"replace"` and keeps one-level undo (`previous_spec_json`); `mode:"add"` appends the agent's new widgets. The new command is stored as `command`.
> **Assumed:** (10) **Rebinding** (`PATCH …/widgets/{wid}`) edits the widget's config only; `description_source` becomes `auto` (deterministic caption + rationale regenerated) unless the user edited the text. No LLM.
> **Assumed:** (11) No Playwright in this repo (as Phase 15): e2e = `TestClient`; UI behaviour verified by pure-function `node --test` files plus the human gate. Lint at zero warnings.
> **Assumed:** (12) `cryptography` is added as an explicit Python dependency (Phase 19 only); `httpx` (already a runtime dependency) is the API-source HTTP client; no new npm dependency in any phase (native DnD continues).
> **Assumed:** (13) Dashboard-level filters are stored on the spec as defaults and can be overridden per request (`?filters=`); they AND-combine with widget-level filters.
> **Assumed:** (14) Phases 16–19 each add at most one Alembic revision (16: none; 17: `previous_spec_json`; 18: `dashboard_templates` + `dashboards.template_id`; 19: `data_sources` + `datasets.source_id`); builder confirms head by content with `uv run alembic heads`.

## Phase
Phase 16 (see `spec/roadmap.md`). Extends [dashboard-builder.md](dashboard-builder.md) (C40).
