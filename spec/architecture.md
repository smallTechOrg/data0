# Architecture

---

## System Overview

A single-user, local web app. A Next.js single-page UI (served single-origin by FastAPI on port 8001) lets the user upload data files and ask plain-English questions. FastAPI routes handle uploads, dataset metadata, and analysis requests. An analysis request runs a LangGraph `StateGraph` ReAct loop: a Gemini LLM (via the project's `LLMClient`) reasons about the question, emits a pandas expression, the agent executes it in a sandboxed namespace, feeds the result back, and iterates until it produces a `FINAL ANSWER:`. Datasets, runs, sessions, and key/value settings persist in SQLite via SQLAlchemy 2.0 (Alembic-migrated). Uploaded files live on local disk as CSV + Parquet. With no LLM key set, a stub provider auto-engages so the whole app works offline.

This design **extends the existing skeleton in place** — the flat `src/` package (project name `agent`), the `AGENT_` env prefix, the `LLMClient`/provider pattern, the `ok()`/`api_error()` envelope, the LangGraph runner, the SQLAlchemy `Base`, and the Next.js `frontend/`. No package is renamed; no nested `src/data_analyst/` is created. Missing modules are ADDED alongside the existing ones.

## Component Map

```
[Next.js UI (frontend/, served single-origin on :8001 /app)]
        │  fetch (JSON / multipart)
        ▼
[FastAPI routers: upload · datasets · ask · sessions · runs · stats · memory · health · dashboards (C40)]
        │                                   │
        ▼                                   ▼
[graph.runner.run_agent()]          [direct SQLAlchemy (no repository layer)]
        │                                   │
        ▼                                   ▼
[LangGraph StateGraph ReAct loop] ←──→ [SQLite via SQLAlchemy 2.0 + Alembic]
        │  setup → plan → execute → finalize
        ▼
[LLMClient → provider (gemini | openrouter | stub)] ←→ [Google Gemini API]
        │
        ▼
[pandas sandbox: df, pd, np, plt, sklearn, save_dataset(...), echart(...)]  ←→ [uploads/*.csv + *.parquet]
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| **UI** (`frontend/`) | Three-tab SPA (Database + Analyse + Dashboard, C40). Calls the REST API. Renders Markdown answers, charts, ER diagram, and the drag-to-rearrange dashboard grid. |
| **API** (`src/api/`) | FastAPI routers; `ok()`/`api_error()` envelope; single-origin static mount of the built Next.js app; lifespan `init_db()`. |
| **Agent** (`src/graph/`) | LangGraph ReAct `StateGraph`, nodes, edges, runner, sandbox (incl. the lazy catalog namespace), pre-flight clarification (C26), graph-adjacent one-shot LLM calls (suggestions/describe/compress). |
| **LLM** (`src/llm/`) | `LLMClient` + provider factory; uniform `call_model(prompt, *, system)` over Gemini / OpenRouter / stub. |
| **Domain** (`src/domain/`) | Pydantic models per entity (request/response + read models). |
| **Storage** (`src/db/`) | SQLAlchemy 2.0 models extending `Base`; lazy engine/session singletons; `init_db()`. Alembic in `alembic/`. Files on disk in `uploads/`. |
| **Config** (`src/config/`) | Pydantic `BaseSettings`, `env_prefix="AGENT_"`, singleton `get_settings()`. |
| **Observability** (`src/observability/`) | structlog config + `get_logger()`. |
| **Connectors** (`src/connectors/`) | Pluggable `DatasetConnector` registry (C36, Phase 9) — a one-time snapshot-pull data-LOADING seam, not a new agent action. `parquet` (internal, wraps the existing upload store) and `postgresql` (external, BETA/flag-gated) are wired; the ReAct loop and sandbox are completely untouched by this layer. See `spec/capabilities/external-db-connectors.md`. |

## Data Flow

1. **Trigger:** the user uploads a file (`POST /upload`) → parsed by pandas, sha256-hashed, duplicate-checked, saved as CSV + Parquet, a `datasets` row created. **Alternate trigger (C36, Phase 9, BETA):** the user connects an external PostgreSQL database (`POST /connections/check` then `POST /connections/import`) → a chosen table is pulled ONCE via `psycopg2` + `pd.read_sql` into a DataFrame and registered through the SAME `datasets` row shape (`origin="connected"`), saved as CSV + Parquet exactly like an upload. From step 2 onward a connected dataset is indistinguishable from an uploaded one.
2. The user asks a question (`POST /ask`) → pre-flight clarification (C26, first turn only) may short-circuit with a clarifying question; otherwise the agent is handed a metadata-only catalog of ALL datasets and picks + lazily loads which it needs inside the graph.
3. A `query_runs` row is created (`status=running`), then `graph.runner.run_agent()` invokes the compiled `StateGraph`.
4. `setup` loads DataFrame(s) (Parquet preferred, CSV fallback; session-cached). `plan_action` calls the LLM (real Gemini or stub) for the next pandas action or a `FINAL ANSWER:`. `execute_action` evals it in the sandbox, captures charts, appends to `action_history`, writes `iteration_count` to the DB for live polling, and loops. `finalize` / `force_finalize` produces the answer.
5. **Output:** `/ask` returns `{type:"answer", run_id, answer_markdown, answer_html, steps, iteration_count, tokens_*, suggested_questions, prompt_breakdown, ...}`; the run row is persisted `status=completed`. The UI renders the Markdown answer, charts, and steps inspector.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Google Gemini API (`google-genai`) | LLM reasoning for the ReAct loop and graph-adjacent calls | Missing key → auto stub mode + yellow banner. API/network error → node logs, routes recoverable errors back to `plan_action`; fatal → `handle_error` sets run `failed` with a clear message. |
| OpenRouter API | Alternate LLM provider | Same envelope as Gemini via `LLMClient`. |
| SQLite (local file) | Persist datasets/runs/sessions/settings | Connection/migration error surfaces at startup / request; never silently ignored. |
| Local disk (`uploads/`) | Store uploaded CSV + Parquet | Write failure on upload → `500` write fail; load failure in `setup` → `handle_error`. |
| PostgreSQL (`psycopg2`, C36, BETA, `AGENT_ENABLE_DB_CONNECTORS`) | One-time bounded snapshot pull of an external table into a dataset (`src/connectors/postgres.py`) | Connect/introspect/pull failure → `DatasetConnectionError` (credential-free) → API `400 connection_failed`; hard 8s wall-clock timeout on connect/introspect. Never a live query path — no runtime dependency once a table is imported. |

## Stack

> This project's concrete technology choices. Generic, every-project rules (model-naming, DB driver, dev port, test environment) live in `harness/patterns/tech-stack.md`; this section is only what **this** project picked. The package stays **`agent`** with a **flat `src/` layout** — no rename, no nested `src/data_analyst/`.

- **Language:** Python 3.12+ (backend) · TypeScript / React 19 (frontend).
- **Agent framework:** LangGraph `StateGraph` (ReAct loop). No LangChain.
- **LLM provider + model:** Google Gemini via `google-genai`; default model `gemini-3.1-flash-lite` (**verified at Phase 2/3 gate**; recorded in README). Alternate provider: OpenRouter. Offline fallback: stub.
- **Backend:** FastAPI + uvicorn, single-origin serving the built Next.js app on port 8001.
- **Database + ORM:** SQLite + SQLAlchemy 2.0 (declarative `Mapped`), Alembic migrations. SQLite is the **production** DB for this single-user local app.
- **Frontend:** Next.js 15 + React 19 (existing `frontend/`), static-exported to `frontend/out/` and mounted at `/app`. Key client libs: `react-markdown` + `remark-gfm` (client-side answer rendering), `echarts` (tree-shaken inline charts, ~0.64 MB).
- **Dependency management:** uv + `pyproject.toml` (Python) · pnpm (frontend).

| Key library | Version | Purpose |
|-------------|---------|---------|
| fastapi | ≥0.115 | HTTP API (already present) |
| uvicorn[standard] | ≥0.30 | ASGI server (already present) |
| langgraph | ≥0.1 | ReAct `StateGraph` (already present) |
| google-genai | ≥2.9 | Gemini provider (already present) |
| sqlalchemy | ≥2.0 | ORM (already present) |
| alembic | ≥1.13 | Migrations (already present) |
| pydantic / pydantic-settings | ≥2.7 / ≥2.3 | Domain models + settings (already present) |
| structlog | ≥24.1 | Structured logging (already present) |
| **pandas** | ≥2.2 | DataFrame analysis in the sandbox (ADD) |
| **numpy** | ≥1.26 | Numerics (ADD) |
| **pyarrow** | ≥16 | Parquet read/write (ADD) |
| **openpyxl** | ≥3.1 | `.xlsx` ingest (ADD) |
| **xlrd** | ≥2.0 | `.xls` ingest (ADD) |
| **echarts** (frontend) | ≥6.1 | Inline charts rendered in the browser via tree-shaken `echarts/core`; the agent sandbox emits ECharts `option` JSON via `echart(...)` |
| **matplotlib** | ≥3.9 | Sandbox plotting (ADD) |
| **seaborn** | ≥0.13 | Sandbox plotting (ADD) |
| **scipy** | ≥1.13 | Stats in sandbox (ADD) |
| **scikit-learn** | ≥1.5 | ML in sandbox (ADD) |
| **statsmodels** | ≥0.14 | Stats models in sandbox (ADD) |
| **markdown-it-py** | ≥3.0 | Markdown → HTML for `answer_html` (ADD) |
| **tabulate** | ≥0.9 | Table rendering in answers (ADD) |
| **python-multipart** | ≥0.0.9 | FastAPI multipart upload parsing (ADD) |
| **psycopg2-binary** | ≥2.9 | PostgreSQL connector (C36) — introspection + snapshot pull only, no live query path (ADD, Phase 9) |

**New settings / env vars (prefix `AGENT_`):** ADD `AGENT_OPENROUTER_API_KEY` (default `""`), `AGENT_MAX_ITERATIONS` (int, default `12`). EXTEND `AGENT_LLM_PROVIDER` valid values to `auto | gemini | openrouter | stub` (blank ⇒ auto-detect from whichever key is set; explicit `stub` when none). `AGENT_LLM_MODEL` overrides the model. `AGENT_GEMINI_API_KEY` is the live key. (`.env.example` is updated to document these; `anthropic` provider stays supported as-is — it is not removed.) ADD `AGENT_ENABLE_DB_CONNECTORS` (bool, default `false`, Phase 9) — gates the entire `/connections/*` surface (C36); when `false` every route except `GET /connections/status` returns `403 connectors_disabled`.

**New `src/` modules (added in place):**

- `src/graph/`: `sandbox.py` (eval namespace + lazy catalog namespace + `save_dataset`), `preflight.py` (C26 clarification), `suggestions.py` (follow-up questions), `describe.py` (C30 notes), `compress.py` (C31 fact extraction), `derived.py` (derived-dataset registration / lineage / staleness), `memory.py` (global-memory block). `state.py`/`nodes.py`/`edges.py`/`agent.py`/`runner.py` are REWRITTEN in place for the ReAct loop.
- `src/llm/providers/`: `base.py` (provider protocol), `stub.py` (node-tag-branching offline provider), `openrouter.py`. `gemini.py` keeps its shape (default-model note only).
- `src/api/`: `upload.py`, `datasets.py`, `datasets_ops.py` (clean/describe/re-derive), `ask.py`, `sessions.py`, `stats.py`, `memory.py`, `settings.py` (`GET`/`PATCH /settings`), `connections.py` (NEW, Phase 9 — C36 connector routes), `dashboards.py` (NEW, Phase 15 — C40); `health.py` + `runs.py` extended.
- `src/domain/`: `dataset.py`, `query_run.py`, `session.py`, `setting.py` (NEW); `run.py` kept.
- `src/config/`: `db_overrides.py` (NEW) — `get_runtime_model()` / `get_runtime_max_iterations()` read the `settings` table so a Settings-panel choice overrides the `.env` default; consumed by `LLMClient._make_provider()` and `runner.run_agent()`.
- `src/prompts/`: `plan_action.md`, `finalize.md`, `clarify.md`, `suggest.md`, `describe.md`, `compress.md`, `clean.md` (NEW). The boilerplate `transform.md` is removed when the ReAct graph replaces `transform_text`.
- `src/connectors/` (NEW, Phase 9): `base.py` (`DatasetConnector` ABC + registry `get_connector()`), `uri.py` (`DatasetURI` — `.raw()`/`.display()`), `parquet.py` (`ParquetConnector`, internal, wraps the existing upload store), `postgres.py` (`PostgresConnector` — `connection_check`/`discover_tables`/`discover_relationships`/`pull_table`, all via `psycopg2`). This is a data-LOADING seam only — no MCP server, no live query tool, no graph/agent involvement. See `spec/capabilities/external-db-connectors.md`.

**Dashboard builder (C40, Phase 15):** a graph-adjacent pipeline, not a graph node — new `src/graph/dashboard_profile.py` (deterministic data profile), `src/graph/dashboard.py` (one structured `LLMClient` call → `validate_spec` → ≤1 repair → deterministic fallback → layout assignment), `src/graph/dashboard_data.py` (the safe pandas aggregation engine that computes widget data from the spec — no LLM-written code, no sandbox), `src/domain/dashboard.py` (Pydantic spec models), `src/api/dashboards.py`, `src/prompts/dashboard.md`, `DashboardRow` in `src/db/models.py`. Reuses `LLMClient`, `_build_echart_option`/`_as_jsonable` (sandbox), the Parquet-first loader, and the C15 cascade. Details and the rejected alternatives: `spec/agent.md` → "Dashboard builder pipeline (C40)". **Frontend:** a new `frontend/src/components/dashboard/` folder and a third tab; drag-and-drop uses the browser's **native HTML5 drag-and-drop (+ keyboard move buttons) over a CSS 12-column grid — NO new npm dependency** (decision: `react-grid-layout` would add a dependency, a CSS import and React-19 peer-dep risk to buy free-form pixel positioning that this auto-packed layout does not need; revisit only if Phase 16 needs free resize/overlap-free collision handling). Charts reuse the existing tree-shaken `echarts` renderer. No new Python dependency.

**Avoid:** LangChain (LangGraph only); the repository pattern (use SQLAlchemy directly in routers/nodes per skeleton convention); Pydantic/dataclass for `AgentState` (use `TypedDict`); calling a provider SDK directly in a node (always go through `LLMClient`); a second top-level package or any rename of `agent`/`src/`; `duckdb` as a dependency (C36 uses native `psycopg2` + `pd.read_sql` only, no DuckDB `ATTACH`); an MCP server or live SQL `query` tool exposed to the agent (C36 is snapshot-import only — a connector never becomes a graph node or a new agent action).

## LLM Provider Design

`LLMClient` is the single path to any provider (no node calls an SDK directly). The factory `_make_provider()` is extended:

- `provider = settings.llm_provider`; if blank, auto-detect: `anthropic_api_key` → `anthropic`; else `gemini_api_key` → `gemini`; else `openrouter_api_key` → `openrouter`; else `stub`. Explicit `stub` always selects the stub. Anthropic is checked first when its key is set (it predates Gemini in the codebase and is retained as a first-class provider).
- Each provider implements TWO methods (Protocol in `base.py`): `complete(prompt, *, system=None) -> LLMResponse` (text + REAL provider-reported `tokens_input`/`tokens_output`, `0` when the provider reports none) and `call_model(prompt, *, system=None) -> str` (the text-only wrapper over `complete`). The graph's `plan_action`/`force_finalize` use `complete()` for accurate token totals; the single-shot graph-adjacent helpers use `call_model`, except `generate_suggestions`/`generate_starter_questions`, which use `complete()` because their token usage is counted toward the run/display totals. `LLMResponse` is a `NamedTuple(text, tokens_input=0, tokens_output=0)`. `LLMClient` also exposes the resolved `provider` name and `model` (so `/health`, `/stats/daily`, and the UI can show the stub banner + active model).
- **Stub provider** branches **only on injected node tags** in the prompt (never on prose): `<node:finalize>` → canned best-effort summary; `<node:plan>` → 1st call returns `df.describe().to_string()`, later calls return a `FINAL ANSWER:` Markdown summary (iteration inferred from `Result:`/`Error:` markers so repeated calls differ); a `<node:plan>` tag missing → `FINAL ANSWER: [stub] Unable to process`. There is no `<node:select>` branch (dataset selection is agent-driven — Phase 6). See `spec/agent.md` for the exact tags and node behavior.
- **Gemini 429 retry:** `GeminiProvider.complete()` wraps only the `generate_content` call in an adaptive retry — 429/`RESOURCE_EXHAUSTED` only, honoring the server's suggested `retryDelay` (exponential 2s/8s/30s fallback), max 3 retries under a ~90s total-wait ceiling, one `gemini_429_retry` warning per retry; any other error (and every other provider) fails fast unchanged.
- **Model verification:** `gemini-3.1-flash-lite` was verified at the Phase 2/3 real-key gate — it resolves against the Gemini API and is the confirmed model in use. It is recorded in `README.md`. No fallback was needed.
- **Model catalogue (bare IDs):** model ids are stored/consumed BARE (no provider prefix). The current selectable set (Settings dropdown + the `_CONTEXT_LIMITS` table in `stats.py`) is the Gemini family — `gemini-3.5-flash`, `gemini-3.1-pro-preview`, `gemini-3-pro-preview`, **`gemini-3.1-flash-lite` (default)**, `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.0-flash`, `gemini-2.0-flash-lite` — plus the Anthropic models (`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`). The retired `gemini-1.5-*` models have been removed. An unknown model id falls back to a `128000` context limit.

## Single-Origin Serving

The built Next.js app is statically exported to `frontend/out/` (the root `agent.py --run` launcher builds it). `create_app()` already mounts it at `/app` when `frontend/out/` exists (`StaticFiles(..., html=True)`), so the UI is at `http://localhost:8001/app/`. The API runs at the root paths (`/health`, `/upload`, `/ask`, ...). Same origin → no CORS. The server starts API-only when `out/` is absent. Run command unchanged from the skeleton: **`python agent.py --run`** (runs migrations + frontend build + uvicorn on :8001). `src/__main__.py` (`uv run python -m src`) remains a lower-level entrypoint that starts uvicorn only.

## Testing Layout

Three test tiers under `tests/` (existing `conftest.py` fixtures are reused and extended):

- `tests/unit/` — **offline stub suite** (zero env vars, in-memory SQLite via the autouse `_isolated_db` fixture, no network). Drives the stub provider; an ADDITIONAL guarantee, never the gate. New `db.models` models flow into `_isolated_db` automatically; `_reset_settings_singleton` keeps settings isolated.
- `tests/integration/` — **real-Gemini** suite using `AGENT_GEMINI_API_KEY` from `.env`. Exercises `/ask`, sessions, pre-flight, derived datasets, cleaning against the real LLM.
- `tests/e2e/` — **golden-path + live-server smoke** through `TestClient` (and a `curl` live-server check) against the real Gemini; asserts response CONTENT.

**Extend `conftest.py` `_require_llm_key`** so its skip condition also recognizes the Gemini/OpenRouter path (skip only when none of `anthropic_api_key`/`gemini_api_key`/`openrouter_api_key` is set). The real-key gates are authoritative per `harness/rules/ai-agents.md` #6/#7; tests run against the production SQLite driver (isolated copy in unit tests is correct, not a substitute).

## Deployment Model

Local, single-process. One start command from the repo root: **`python agent.py --run`** (runs migrations, builds the frontend, starts uvicorn on `0.0.0.0:8001`). SQLite file at `AGENT_DATABASE_URL` (default `sqlite:///./data/agent.db`). Uploaded files under `uploads/`. No container or cloud required. Migrations can also be applied directly with `uv run alembic upgrade head` from the repo root; the lower-level server entrypoint is `uv run python -m src`.
