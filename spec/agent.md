# Agent

> Required: this project uses LangGraph. This file specifies the full ReAct `StateGraph`. It REWRITES the skeleton's `transform_text` graph in place (`src/graph/state.py`, `nodes.py`, `edges.py`, `agent.py`, `runner.py`) and ADDS `sandbox.py`, `preflight.py`, `suggestions.py`, `describe.py`, `compress.py`, `derived.py`, `memory.py`.

---

## Agent Architecture Pattern

| Pattern | Use when |
|---------|----------|
| **Single-agent loop** | One LLM drives a deterministic tool-call loop. No branches, no handoffs. |
| **Graph (LangGraph)** | Multi-step pipeline with conditional edges, checkpointing, or parallel nodes. |
| **Multi-agent** | Specialised sub-agents with distinct roles; orchestrator routes between them. |
| **Supervisor** | One supervisor LLM dispatches to worker agents based on task type. |
| **Human-in-the-loop** | Execution pauses at defined checkpoints for user review or approval. |

**Chosen:** **Graph (LangGraph) ReAct loop.** A single LLM reasons and emits one pandas action per turn; the agent executes it and feeds the result back, iterating with conditional edges (self-correct on error, force-finalize on max-iter / consecutive errors). The conditional edges, the iteration/error counters, and the live DB-write-per-step rule make this a graph, not a flat loop.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `plan_action` (per-iteration reasoning) | Gemini | `gemini-3.1-flash-lite` (**verified at Phase 2/3 gate**) | Cheapest fast model that follows the ReAct format; called every iteration, so latency/cost dominate. |
| `force_finalize` (synthesis) | Gemini | same | One synthesis call; quality-over-cost but the same model is sufficient. |
| `check_clarification` (C26/C37), `generate_suggestions`, `generate_starter_questions` (C37), `generate_dataset_notes` (C30), `extract_facts` (C31) | Gemini | same | Single-shot helpers outside the graph; same model via `LLMClient`. |

All calls go through `LLMClient` — **never the provider SDK directly**. The client exposes two methods (both implemented by every provider, contract in `src/llm/providers/base.py`):

- `complete(prompt, *, system=None) -> LLMResponse` — returns the text plus REAL provider-reported token usage (`tokens_input`/`tokens_output` from the provider's usage metadata; `0` when a provider reports none, so the caller falls back to a `chars/4` estimate). The per-iteration `plan_action` and `force_finalize` use `complete()` so the run's token totals are accurate.
- `call_model(prompt, *, system=None) -> str` — the text-only convenience wrapper over `complete()`. Most graph-adjacent single-shot helpers (`check_clarification`, `generate_dataset_notes`/describe, `extract_facts`/compress, clean) use `call_model`; `generate_suggestions` (and `generate_starter_questions`) use `complete()` directly, because their real provider token usage is added to the run/display totals.

`LLMResponse` is a `NamedTuple(text, tokens_input=0, tokens_output=0, tokens_cached=0)` — `tokens_cached` (C39, Phase 14) is how many of `tokens_input` were served from the provider's prompt cache (Gemini reads `usage_metadata.cached_content_token_count`, absent/None → 0; anthropic/openrouter/stub leave the default 0 — honest, they make no cache-control calls). Provider is auto-detected (Anthropic key → anthropic; else Gemini → gemini; else OpenRouter; else stub). Model override via `AGENT_LLM_MODEL`.

**Fallback behaviour:** No key → stub provider auto-engages (yellow UI banner). A Gemini API/network error inside `execute_action`'s recoverable path or a `plan_action` transient error routes back to `plan_action` to retry the reasoning; a fatal load/setup error routes to `handle_error` (run `failed`, clear message). `force_finalize` falls back to a static best-effort message if its single LLM call fails. This is production resilience — tests call the real Gemini with keys from `.env`.

**Prompt strategy:** System/user split. `plan_action` prompt is assembled from question + `action_history` (Action/Result/Error transcript) + `conversation_history` + `dataset_context` (the metadata-only catalog of ALL datasets — see Pre-flight / setup) + persistent memory, with an injected `<node:plan>` tag. The model must reply either `FINAL ANSWER: <markdown>` or a bare pandas expression to execute; it references datasets by variable name and they load on demand. Helpers (`clarify`, `suggest`, `describe`, `compress`) request structured output (JSON arrays / a single question / plain text) and carry their own `<node:...>` tags where the stub must branch.

---

## Tools & Tool Calling

The agent does not use the LLM-native tool-calling API; its single "tool" is **eval of a pandas expression** the model emits as text, executed in a fixed sandbox namespace. The sandbox functions:

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| pandas eval (`execute_action`) | Eval/exec the model's expression against the loaded DataFrame(s) | expression string | stringified result (+ captured ECharts `option` JSON from `echart(...)`) | none on the DataFrame in place (read-mostly); captures charts |
| `save_dataset(df, name, desc)` | Materialise a DataFrame as a registered DERIVED dataset | DataFrame, name, description | confirmation string | writes `uploads/{id}.csv` + `.parquet`; inserts a `datasets` row (origin=derived) with `derivation_code` + parents + producing run (C25); ALSO injects the frame into the run namespace as a `<name>` variable for later steps, and appends the new id to the session so later turns load it |

**Sandbox namespace** (provided to `execute_action`): a **lazy** namespace over the dataset *catalog* (`build_lazy_namespace`). `df` (first catalog dataset), `df1`/`df2`/… (per-dataset, ordered as listed in the catalog), and a `<filename_stem>` alias per dataset each resolve to their DataFrame **the first time the model references one** — loaded on demand (`_loader`), then cached for the run and recorded in the run's used-set (`_loaded_ids[run_id]`). Also present: the libraries `pd, np, plt, sns, scipy, stats, sklearn, sm`, plus `save_dataset` and `echart` (charts). There is no Plotly in the namespace. No filesystem/network builtins beyond these are exposed. **State across steps:** the SAME namespace object is persisted on the run's `_dataframes[run_id]` bundle and reused across every iteration of a run (only `save_dataset`/`echart`, whose accumulators are inherently per-call, are rebound each step) — so ordinary assigned variables (e.g. `tmp = df1.head(3)`) DO carry forward to later steps of the same run, exactly like successive cells in one Jupyter kernel. `save_dataset` is no longer needed just to survive to the next step; its real purpose is different and still necessary: it makes a frame a first-class, browsable DERIVED dataset with recorded lineage that persists ACROSS runs/turns/sessions (not just within one run) — it adds the saved frame to the run's derived frames (so it's also directly referenceable as `<name>` for the rest of THIS run) and, via `POST /ask` appending the new id to the session's `dataset_ids_json`, a LATER turn loads it too. Use it when the result should outlive this run and show up in the Database tab (C25); ordinary variables already suffice for chaining steps within one run.

**Eval semantics (`sandbox.eval_expression`):** the action is tried as a single `eval` first (the common case). On a `SyntaxError` (multi-statement actions) the block is `ast`-parsed: everything BEFORE the trailing expression is `exec`'d, and that trailing expression is `eval`'d **EXACTLY ONCE**. This is what makes a side-effecting tail like `save_dataset(df, …)` run a single time — the earlier "exec the whole block, then eval the last line" approach double-ran the tail and registered a derived dataset twice. `save_dataset(df, name, desc)` is documented to the model in `plan_action.md` (call it to create/persist a derived table); the sandbox extracts the df-producing first-argument expression (not the wrapping `save_dataset(...)` call) as the derived dataset's `derivation_code` for `/re-derive` (C25).

**Tool selection strategy:** The LLM chooses the next pandas expression each iteration (free-form reasoning). The agent does not route between multiple tools — it either executes the expression or, on `FINAL ANSWER:`, finalizes.

**Tool failure handling:** An exception in `execute_action` is caught, recorded as `{action, result, is_error: true, reasoning}` in `action_history`, and the graph routes **back to `plan_action`** so the model self-corrects (recoverable). Three consecutive errors → `force_finalize`. A fatal error (e.g. DataFrame load failure in `setup`) → `handle_error`.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                          # set at initialisation (query_runs.id)

    # Input
    dataset_ids: list[str]               # ALL workspace datasets as the agent's catalog (it picks + lazily loads)
    dataset_context: str | None          # metadata-only catalog of all datasets, injected into the prompt
    session_id: str | None               # set when the run belongs to a conversation session
    question: str                        # the user's plain-English question
    conversation_history: list[dict]     # prior turns {question, answer} for the session

    # Pipeline data (populated progressively by nodes)
    action_history: list[dict]           # [{action, result, is_error, reasoning}] appended by execute_action (reasoning="" when the model emitted no REASONING: line, C33)
    iteration_count: int                 # incremented by plan_action
    llm_response: str                    # latest raw model reply (action or FINAL ANSWER)
    tokens_input: int                    # accumulated prompt tokens
    tokens_output: int                   # accumulated completion tokens
    tokens_cached: int                   # C39: accumulated cache-served prompt tokens (subset of tokens_input; plan_action + force_finalize only)
    charts: list[str]                    # ECharts `option` JSON strings captured in execute_action (via echart())
    prompt_component_chars: dict         # C29: CUMULATIVE per-bucket char counts summed across all plan_action calls (used to build the prompt_breakdown)

    # Output
    answer: str | None                   # final markdown answer (FINAL ANSWER stripped)
    selector_reasoning: str | None       # retained for API/DB compat; always None under agent-driven selection

    # Control
    error: str | None                    # set by any node on fatal failure → handle_error
    status: str                          # running | completed | failed
    error_message: str | None            # informational: "max_iterations" | "consecutive_errors" (set by force_finalize) or the fatal error string (set by handle_error); persisted to query_runs
    max_iterations: int                  # iteration cap for this run (from settings.max_iterations or the /ask override)

    # Chart guardrail (deterministic): when the question explicitly asks for a
    # chart, force ONE extra iteration demanding an echart(...) if a final reply
    # arrives with no chart produced. Capped so it can never loop forever.
    wants_chart: bool                    # set in setup from _wants_chart(question)
    chart_force_count: int               # times a final-without-chart was rejected (cap 2)
```

This replaces the skeleton's 4-field `AgentState`. `TypedDict, total=False` per skeleton convention (not dataclass/Pydantic).

---

## Nodes / Steps

### `setup`

**Reads:** `dataset_ids`, `session_id`, `run_id`. **Writes:** `dataset_context`, `error` (on fatal). **LLM:** no.

**Behaviour:** For each `dataset_id`, check the session DataFrame cache (C27) keyed by `session_id` — on hit reuse + LRU-touch; on miss load Parquet (preferred) or CSV (fallback) and cache. Single-turn (no `session_id`) uses a run-scoped `_dataframes[run_id]` dict instead. Build `dataset_context` from each dataset's notes/facts and column schema. A fatal load/lookup error sets `error` → routes to `handle_error`. (Cache logic lands in Phase 3; Phase 2's `setup` is the simple per-run load.) **Per-turn isolation contract (Phase 11):** the cache never hands out the stored frame object itself — `_session_load_frame` returns a shallow copy (`frame.copy(deep=False)`) on BOTH the hit and miss paths. Under pandas-3 always-on Copy-on-Write that copy is a near-zero-cost lazy snapshot: an in-place mutation by one turn's generated code (e.g. a `to_datetime` dtype change) triggers per-column copy-on-write on the returned copy, so the cached original stays pristine and later turns of the session NEVER see another turn's mutations. Within a single run, the same returned object flows through that run's `_dataframes[run_id]` namespace, so intra-run self-visibility of mutations is unchanged — the isolation boundary is per-turn, not per-step. (`pd.options.mode.copy_on_write` must NOT be set anywhere — it is a deprecated no-op in pandas 3.x, where CoW is always on.)

| System | Operation | On Failure |
|--------|-----------|------------|
| Disk (`uploads/`) | read Parquet/CSV into DataFrame | fatal → set `error` |
| SQLite | load dataset metadata | fatal → set `error` |

### `plan_action`

**Reads:** `question`, `action_history`, `conversation_history`, `dataset_context`, `iteration_count`. **Writes:** `llm_response`, `iteration_count` (+1), `tokens_input`, `tokens_output`, `tokens_cached` (C39: accumulated alongside `tokens_input` from `resp.tokens_cached`; also accumulated in `force_finalize`, NOT in `generate_suggestions` — documented scope bound), `prompt_component_chars` (C29: accumulates this iteration's per-bucket char counts into the cumulative dict). **LLM:** yes — `plan_action.md` system prompt + assembled context + injected `<node:plan>` tag.

**Behaviour:** Assemble the prompt (question + Action/Result/Error transcript + conversation history + dataset context + persistent memory + column schema), call the LLM, store the reply, increment `iteration_count`, add token counts. When `iteration_count >= max_iterations - 2`, append a wrap-up instruction telling the model to produce `FINAL ANSWER:` now from its best findings (no extra LLM call). A fatal LLM error sets `error`.

### `execute_action`

**Reads:** `llm_response`, `action_history`, `iteration_count`, the loaded DataFrame(s). **Writes:** `action_history`, `charts`. **LLM:** no.

**Behaviour:** First split an OPTIONAL leading `REASONING:` line off `llm_response` (C33): if the first non-empty line starts with `REASONING:` (case-insensitive), its text is this step's `reasoning` and the REMAINDER flows on unchanged; otherwise `reasoning=""` and the whole reply flows on. Then run the (remaining) planner reply through `_extract_code` — it strips a ```` ```python ```` / bare ```` ``` ```` fence (taking the LAST fenced block when several are present) and inline-code backticks (`` `expr` ``), falling back to the bare reply — so a model that wraps its action in a fence + reasoning prose still has its REAL code executed instead of `eval()` choking on the prose. Then eval/exec the extracted pandas expression in the sandbox namespace; capture charts into `charts` by reading the per-run accumulator populated by the `echart(...)` helper (each call builds an ECharts `option` dict, which the node `json.dumps`-es into `charts`); convert the result to a string; append `{action, result, is_error, reasoning}` to `action_history` (`reasoning=""` when no `REASONING:` line was emitted, C33); write `iteration_count` to the DB each step for live progress polling (`GET /runs/current`). On exception, mark `is_error=true` and route back to `plan_action` to self-correct (recoverable). 3 consecutive errors OR max-iter → `force_finalize`. A non-recoverable fatal error → `handle_error`.

| System | Operation | On Failure |
|--------|-----------|------------|
| SQLite | write `iteration_count` for live polling | log + continue |
| Disk | `save_dataset` writes CSV+Parquet | record error in step, route to plan_action |

### `finalize`

**Reads:** `llm_response`, `charts`, `action_history`, `run_id`. **Writes:** `answer`, `status=completed`. **LLM:** no.

**Behaviour:** Strip the leading `FINAL ANSWER:` prefix, append chart divs (from `charts`), set `status=completed`, persist `answer` + `action_history` + token counts to the `query_runs` row, release the run-scoped DataFrame.

### `force_finalize`

**Reads:** `action_history`, `question`, `run_id`. **Writes:** `answer`, `status=completed`. **LLM:** yes — ONE synthesis call with `finalize.md` + injected `<node:finalize>` tag (EXCEPT on user cancellation, see below).

**Behaviour:** Fires on max-iter OR 3 consecutive errors. One synthesis LLM call; `status` is ALWAYS `completed`; set `error_message = "max_iterations"` or `"consecutive_errors"` on the run (informational, not a failure). Falls back to a static best-effort message if the call fails.

**Cooperative cancellation (Stop button):** A `POST /runs/{run_id}/cancel` flags the run in a thread-safe registry (`graph.cancellation`). `plan_action` (skips its LLM call), `after_plan`, and `after_execute` check `is_cancelled(run_id)` and route to `force_finalize`, which — when cancelled — SHORT-CIRCUITS its synthesis call and returns a fixed `_Run stopped by the user before it finished._` answer with `error_message="cancelled"`; the runner also skips follow-up suggestions. Net effect: pressing Stop makes the loop wrap up within ~one step and issues NO further model calls. The runner `discard`s the flag when the run ends. Cancellation is cooperative, so it takes effect once the run is underway (the UI gets the `run_id` from the progress poll); an early Stop still aborts the client request immediately.

### `handle_error`

**Reads:** `error`, `run_id`. **Writes:** `status=failed`. **LLM:** no.

**Behaviour:** Fatal errors → set `status=failed`, persist `error_message`, release the DataFrame, terminate.

---

## Graph / Flow Topology

```
START
  │
  ▼
setup ──(error)──► handle_error ──► END
  │ (ok)
  ▼
plan_action ──(fatal error)──────► handle_error ──► END
  │     │
  │     └──(FINAL ANSWER: in llm_response)──► finalize ──► END
  ▼ (action)
execute_action ──(fatal error)───► handle_error ──► END
  │     │
  │     └──(3 consec errors OR iteration_count ≥ max_iter)──► force_finalize ──► END
  ▼ (ok or recoverable error)
plan_action   (loop)
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| `setup` | `state.get("error")` | `handle_error` |
| `setup` | else | `plan_action` |
| `plan_action` | `state.get("error")` | `handle_error` |
| `plan_action` | `"final answer:"` in `llm_response.lower()` and chart guardrail satisfied | `finalize` |
| `plan_action` | chart guardrail: `"final answer:"` in reply AND `wants_chart` AND no charts AND `chart_force_count < 2` | `plan_action` (self-loop) |
| `plan_action` | else (an action to run) | `execute_action` |
| `execute_action` | `state.get("error")` (fatal) | `handle_error` |
| `execute_action` | 3 consecutive `is_error` OR `iteration_count >= max_iterations` | `force_finalize` |
| `execute_action` | else (ok / recoverable error) | `plan_action` |
| `finalize` / `force_finalize` / `handle_error` | always | `END` |

**Termination signal:** case-insensitive substring `FINAL ANSWER:` in `llm_response` (tolerate preamble before it). `MAX_ITERATIONS` = `settings.max_iterations` (env `AGENT_MAX_ITERATIONS`, default **12** — enough for heavy multi-step pipelines like clustering; overridable per-instance via the `max_iterations` Settings/DB value, or per-run via the `/ask` arg).

---

## Pre-flight (before the graph — one one-shot `LLMClient` call)

Runs in the runner, BEFORE the graph, on the FIRST turn of a conversation only (`run_clarification=True`); skipped on follow-ups (the history disambiguates) and when `skip_clarification=true`. Lives in `src/graph/preflight.py`.

1. **C26 clarification (+ C37 refined candidates)** — `check_clarification(question, schemas)` (tag `<node:clarify>`): ONE call returns either "proceed" (→ `None`) or a `ClarificationResult` NamedTuple `(question, suggestions)` — the clarifying question PLUS up to 3 refined candidate questions the user could tap instead of typing (the run returns early `type:"clarification"` with `suggested_questions`, status `clarification`, no graph run). The candidates ride the SAME single call — the pre-flight path gains no extra roundtrip. Reply grammar: exactly `proceed`, or a JSON object `{"question": ..., "suggestions": [...]}` parsed via `{...}`-span extraction; ANY parse failure falls back to treating the whole reply as the clarifying question with `suggestions=[]` (the pre-C37 behavior), and an LLM error still fails open to proceed. Full contract in `spec/capabilities/suggested-questions.md`.

**Dataset selection is NOT a pre-flight step.** It is agent-driven inside the graph: `setup` builds a metadata-only *catalog* of ALL datasets (`{id, filename, alias, columns, notes}`, no frames read) into `dataset_context`, and the ReAct loop picks + lazily loads whichever the question needs (see Tools & Tool Calling → Sandbox namespace). There is no `select_datasets` call and no `<node:select>` tag.

---

## Graph-adjacent single LLM calls (not graph nodes)

- `generate_suggestions(question, answer)` (`src/graph/suggestions.py`) → up to 3 short follow-up questions (JSON array; `[]` on failure); tokens added to the run total.
- `generate_starter_questions(catalog_text)` (`src/graph/suggestions.py`, C37) → up to 3 session-start questions for `GET /suggestions/starters`, from a **metadata-only** catalog (`columns_json` + compressed `context_facts` — no frames loaded, mirroring `setup`'s catalog). Reuses the module's JSON-array parsing + ≤3 cap and injects the SAME `<node:suggest>` tag (identical reply grammar, so the stub needs no new branch). `[]` on any failure; belongs to NO run, so its tokens are not attributed anywhere (accepted gap). Prompt: `src/prompts/starters.md`. See `spec/capabilities/suggested-questions.md`.
- `generate_dataset_notes()` (`src/graph/describe.py`, C30) → sample 50 rows, ask for ≤300-word plain notes, write to `dataset.context`, track `auto_notes_status`, then trigger C31. The single LLM call is **retried up to 3× with backoff** (transient rate-limit/timeout self-heals instead of a spurious `failed`) and is serialized across datasets by a **process-wide lock** so concurrent upload-time describes (one daemon thread per uploaded file) don't all hit the provider at once; only the API call holds the lock (the backoff sleeps are outside it). Outcome is unchanged — still ONE successful call's notes, still never raises.
- `extract_facts()` (`src/graph/compress.py`, C31) → one LLM call → JSON array of ≤20 facts; fills `dataset.context_facts` and `settings.global_memory_facts`; async fire-and-forget self-heal variants with an in-flight lock; failures return `[]`.

---

## Dashboard builder pipeline (C40) — graph-adjacent, NOT a ReAct graph

Triggered by `POST /datasets/{id}/dashboards` (`spec/api.md`); entry point `build_dashboard(dataset_id, command, title=None) -> DashboardBuild` in `src/graph/dashboard.py`. It is a **fixed linear pipeline** like the pre-flight and the graph-adjacent single LLM calls above — it is deliberately NOT wired into the LangGraph `StateGraph`, does not touch `AgentState`, the sandbox, or `/ask`, and creates no `query_runs` row. Observability: structlog events `dashboard_profile`, `dashboard_llm` (latency, tokens, attempt), `dashboard_validate` (error codes), `dashboard_fallback`, `dashboard_done` — no LangSmith trace (no graph).

> **Decision (document, do not re-litigate): spec-JSON + server-side aggregation engine, not sandbox code or a ReAct loop.** Alternatives considered: (a) a ReAct loop that writes pandas/`echart(...)` per widget — rejected: 3–10 LLM roundtrips (30–90 s), non-deterministic output, nothing durable to persist or re-render, and model-written code in the request path; (b) one LLM call that returns per-widget pandas code run in the existing sandbox — rejected: same code-safety/persistence problems, plus the stored dashboard would silently break when the dataset changes. **Chosen:** the LLM emits only a declarative JSON spec (the "what"); a fixed engine (`src/graph/dashboard_data.py`) computes the "how" with a closed set of pandas operations (filter → `groupby/resample` → one of 7 aggregations → sort/limit). This gives one LLM call, strict validation against real columns, deterministic recompute on every open, a stored artefact the UI can rearrange, and a natural seam for the Phase 16 field-drag reconfigure (edit a binding → recompute, no LLM). What is reused: `LLMClient` (all providers), the dataset loader (`_load_dataframe`, Parquet-first), `_build_echart_option` + `_as_jsonable` from `src/graph/sandbox.py` for chart options, `graph.derived` helpers for `uploads/` paths, the ECharts renderer on the frontend. `save_dataset`/derived datasets are NOT used in v1 (a widget-as-derived-dataset action is a Phase 16+ idea).

**Steps (all synchronous inside the request):**

1. **`profile_dataframe(df, notes)`** (`src/graph/dashboard_profile.py`, deterministic, zero LLM): over the FULL frame (cheap, vectorised) per column → `{name, dtype_alias, role, null_pct, nunique, stats}` where `role` ∈ `measure` (numeric, high cardinality), `dimension` (text/bool/category or low-cardinality numeric/int, nunique ≤ 50), `time` (datetime64, or object that parses as dates ≥95% — coerced with `pd.to_datetime(errors="coerce")`), `id` (unique-ish identifier: nunique/rows > 0.9 and non-measure name hint `id|key|code|uuid`), `text` (free text, nunique/rows > 0.5 and avg length > 40). `stats`: numeric → min/max/mean/sum; categorical → top-5 `(value, count)`; time → min/max. Caps: ≤60 columns profiled (rest listed by name+dtype), cell strings truncated to 40 chars, ≤5 sample rows. Output is both a dict (for the fallback generator + validation) and a compact JSON text (≤~6000 chars) for the prompt. Also yields the `columns_schema` (name → dtype alias) used by the validator.
2. **ONE structured LLM call** (`LLMClient().complete(prompt, system=...)`, tag `<node:dashboard>`, prompt `src/prompts/dashboard.md`). Prompt carries: the command, the profile text, the dataset notes (`context_facts` rendered like the catalog, ≤1500 chars), the closed schema (widget kinds, aggregation ops, chart types, field-binding rule "use ONLY these column names", limits), 1 short worked example, and "Reply with ONLY a JSON object `{title, description, widgets:[…]}`; NO layout coordinates; 4–10 widgets; at least one kpi and one chart unless the data cannot support them". Reply grammar: bare JSON object, fenced blocks tolerated, `{…}`-span extraction on prose (same tolerance as `check_clarification`).
3. **`validate_spec(spec, columns_schema)`** (pure function, `src/graph/dashboard.py`, backed by the Pydantic models in `src/domain/dashboard.py`): widget-by-widget; snaps field names; clamps ranges; returns `(clean_widgets, errors[{widget_index, code, detail}])`. Unknown kind/shape or an unsatisfiable binding is an error for that widget; the whole reply being non-object is `bad_json`/`bad_shape`.
4. **Repair (≤1):** if step 3 produced errors and the reply was parseable, ONE more `complete()` call with the same prompt + `## Validation errors` (the code+detail list) + "return the corrected full JSON". Re-validate. Total LLM calls per build ≤ 2.
5. **Resolve:** keep valid widgets; every still-invalid widget is DROPPED (→ `generation.dropped_widgets`); then if zero widgets remain, or the reply was unparseable after the repair attempt, or any LLM call raised → **fallback**: `fallback_spec(profile, command)` (deterministic, no LLM): KPI "Rows" (`count`, `field:null`); up to 3 KPIs of `sum` over the first measures (in column order, skipping columns whose role is `id`); a `bar` of the first measure by the first dimension (`sum`, top 10, `y_desc`); a `line` of the first measure over the first time column (`month`/auto grain) if a time column exists, else a `histogram` of the first measure if one exists; a `table` of the first ≤8 columns (raw, `limit 10`). Datasets lacking measures/dimensions/time simply omit the corresponding widgets (the Rows KPI + raw table always exist). If the agent output is valid but lacks a `kpi` or a `chart`, the missing kind is **supplemented** from the same generator (`generation.supplemented`).
6. **Layout:** `assign_layout(widgets)` (algorithm + contract vector in `spec/api.md`). The final spec is re-validated one last time (cheap) as a safety net before persisting.
7. **Compute:** `compute_widget_data(df, spec)` for the response (`dashboard_data.py`, below). The row is persisted BEFORE the response is built so a client disconnect never loses it; any `compute` exception for a widget becomes that widget's `status:"error"`.

**Aggregation engine (`dashboard_data.py`, closed op set — the safety boundary):** operates on a copy of the loaded frame (never mutates the session cache); per-widget: `apply_filters` (ops `eq ne gt gte lt lte in not_null`, value coerced to the column dtype, failure → widget error) → by kind: **kpi** `df[field].agg(op)` (`count`/`field:null` → `len`); **chart bar/pie** `groupby(x)[y.field].agg(op)` (+ `series_by` pivot, top-8 + "Other") → sort → `head(limit)`; **line/area** x coerced to datetime → `resample`/`Grouper(freq=time_grain)` (or ordered groupby for numeric x) → agg → `x_asc`; **scatter** raw numeric pairs, evenly sampled to ≤2000; **histogram** `np.histogram(x, bins)` → bar option; then the ECharts `option` via `_build_echart_option` (area = line + `areaStyle`; histogram = bar of bin-range labels) → `_as_jsonable`; **table** raw `[columns].sort_values.head(limit)` or `groupby(group_by).agg(...)` (`alias` names) → rows with preview formatting. No `eval`/`exec`, no string-built expressions: fields are used only as dict/column keys after validation, ops are looked up in a fixed `{name: pandas-agg-name}` map.

**Concurrency / blocking:** the pipeline is synchronous and runs in the FastAPI threadpool (sync route), like `/ask`. A per-process lock is NOT needed (stateless; no shared mutable registry).

**Failure matrix:** LLM exception / timeout (incl. Gemini 429-retry exhausted) → fallback, `generation.notes += ["LLM unavailable: <class>"]`; unparseable → repair attempt → fallback; partially invalid → repair → drop → supplement; profile failure (dataset unreadable) → `500 dashboard_failed`, nothing persisted; stub provider (returns `FINAL ANSWER: [stub] …`, not JSON) → fallback (this is the offline behaviour by design and is what the unit suite exercises; real-model behaviour is covered by the scoped real-key test).

**Not covered here (Phase 16+):** editing bindings by dragging fields (the engine already supports it: a changed binding is just a new spec to validate + recompute), regenerate on an existing dashboard, multi-dataset joins.

---

## Stub provider node-tag branching

The stub provider (offline fallback) branches **only on the injected node tag**, never on prose keywords:

| Injected tag | Stub output |
|--------------|-------------|
| `<node:finalize>` | canned best-effort summary string |
| `<node:plan>` (1st call) | `df.describe().to_string()` (relies on `df` → first catalog dataset, loaded on reference) |
| `<node:plan>` (later call) | a `FINAL ANSWER:` markdown summary (iteration inferred from count of `Result:`/`Error:` markers so repeated calls differ) |
| `<node:plan>` missing | `FINAL ANSWER: [stub] Unable to process` |
| `<node:clarify>` | "proceed" (no clarification in stub mode — and therefore no C37 refined candidates either; the extended reply grammar is a real-model-only path) |
| `<node:suggest>` | `[]` (serves BOTH callers of this tag: follow-up suggestions and the C37 starters call — offline starters are empty and the UI hides the block) |
| `<node:dashboard>` | no branch (C40) — falls through to `_PLAN_FALLBACK` (`FINAL ANSWER: [stub] …`, not JSON). The dashboard pipeline treats that as an unparseable reply and returns the deterministic fallback dashboard (`used_fallback=true`) — by design, so the offline suite exercises the fallback path with no stub change. Unit tests of the repair/validation paths inject fake `LLMClient` replies (monkeypatch), never the stub. |
| `<node:describe>` | no branch — falls through to `_PLAN_FALLBACK`; returns `"FINAL ANSWER: [stub] Unable to process"`. `generate_dataset_notes` still sets `auto_notes_status="done"` but stores placeholder text. Real notes require a live Gemini key. |
| `<node:compress>` | no branch — falls through to `_PLAN_FALLBACK`; returns non-JSON. `_parse_facts` in both `graph.compress` and `graph.memory` catches the parse failure and returns `[]` gracefully. Used by C31 `extract_facts` (dataset-scoped) and `compress_memory` (global memory). |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph `AgentState` | question, action_history, charts, tokens, iteration_count |
| **Within a session (frames)** | session DataFrame cache (C27, `_session_cache` in `src/graph/nodes.py`) | loaded DataFrames reused across turns (LRU-bounded); each turn receives a per-turn shallow-copy snapshot of the cached frame (pandas-3 always-on CoW makes this near-zero cost), so turns never see another turn's in-place mutations — the cached original keeps its on-disk dtypes/values until `invalidate_dataset_cache` evicts it (Phase 11) |
| **Across runs** | SQLite `settings` (`global_memory`, `global_memory_facts`) | user-authoritative global memory text (≤ 4000 chars, enforced at `PATCH /memory`) + compressed facts; `get_memory_block()` injects FACTS-ONLY into every `plan_action` prompt once facts exist, falling back to the raw text only when there are no facts yet (never both — sending raw text plus a summary of it is pure per-iteration token waste) |
| **Conversation** | `conversation_sessions` + `query_runs` (`session_id`) | prior turns; loaded into `conversation_history` for multi-turn |
| **Dataset notes** | `datasets.context` / `context_facts` | per-dataset notes injected into `dataset_context` |

**Context window management:** `dataset_context` uses notes/compressed facts rather than full data; `action_history` is the running transcript (each entry `{action, result, is_error, reasoning}`, where `reasoning` is the per-step C33 rationale, `""` when the model emitted no `REASONING:` line). The C29 `prompt_breakdown` carries the five components (system_overhead, dataset_schemas, memory, history, action_history — dataset notes are folded into `dataset_schemas`, not a separate bucket) **scaled to sum EXACTLY to** `total_prompt` (= the run's real cumulative `tokens_input`), plus `tokens_output` (the run's real cumulative output). See `spec/capabilities/context-window-display.md`. When approaching `max_iterations`, the wrap-up instruction forces a `FINAL ANSWER:` rather than growing the context further.

---

## Human-in-the-Loop Checkpoints

The pre-flight **clarification** (C26) is the only pause: an ambiguous question returns `type:"clarification"` with a `clarification_question` plus up to 3 tap-able refined candidate questions (`suggested_questions`, C37 — same single call); the user either re-submits with `skip_clarification:true`, types an answer, or taps a candidate (which fills the composer). No mid-run pauses.

---

## Error Handling & Recovery

**Node-level:** each node catches its own exceptions. Recoverable execution errors are recorded in `action_history` and looped back to `plan_action`. Fatal errors set `state["error"]` and route to `handle_error`.

**Graph-level (`handle_error`):** reads `state.error`, `state.run_id`; updates the `query_runs` row → `status=failed`, `error_message`; logs with `run_id` context; releases the DataFrame; terminates.

**Runner-level (`try/finally` — the exception-safe release guarantee, Phase 11):** the three terminal nodes are NOT the only release path. The runner wraps the graph invoke in a `try/finally` whose `finally` releases all three run-scoped registries — `_dataframes` (via the module-private `_release_dataframe` or a thin public wrapper), `_loaded_ids` (`release_loaded_ids`), and `_derived_created` (`release_derived_created`). All three are idempotent `pop(run_id, None)`, so the double release on the normal path is harmless, and the registries (including the persisted eval namespace) are freed on EVERY exit path from a run — including an uncaught exception escaping any node, which previously leaked them for the process lifetime. The success path's registry READS (`get_loaded_ids`/`get_derived_created`) happen inside the `try`, before the `finally` releases them.

**Resume / retry:** no checkpointer — runs are short and single-shot; a failed run is re-issued as a new `/ask`. (No `SqliteSaver` needed; no long-running pause beyond the synchronous clarification short-circuit.)

**Partial failure:** a failed `save_dataset` or a failed chart capture is recorded as a step error and does not abort the run — the agent continues and finalizes with what it has. A failed `generate_suggestions` or `generate_starter_questions` returns `[]`; an unparseable C37 extended-clarify reply degrades to the plain clarifying question with no candidates (never blocks the clarification).

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Trace** | one logical run per `run_id`, one log line per node | structlog (stdout, JSON) |
| **LLM calls** | accumulated `tokens_input`/`tokens_output`/`tokens_cached` (C39), model | `query_runs` row + structured log |
| **Tool calls** | each pandas action: expression, result/error | `query_runs.action_history` + log |
| **Run outcome** | status, iteration_count, error if any | `query_runs` row + log |

---

## Concurrency Model

- **Run isolation:** single-user, one run at a time per request; `GET /runs/current` returns the most recent run for ~1/s live polling. Runs are scoped by `run_id`; no global lock needed for the single-user model.
- **Parallel nodes within a run:** none — the ReAct loop is strictly sequential.
- **Checkpointing:** none (no `SqliteSaver`/`PostgresSaver`); runs are short-lived and not resumable. The C31 compression's async self-heal uses an in-flight lock (not a graph checkpoint).

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import setup, plan_action, execute_action, finalize, force_finalize, handle_error
from graph.edges import after_setup, after_plan, after_execute

def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("setup", setup)
    g.add_node("plan_action", plan_action)
    g.add_node("execute_action", execute_action)
    g.add_node("finalize", finalize)
    g.add_node("force_finalize", force_finalize)
    g.add_node("handle_error", handle_error)

    g.set_entry_point("setup")
    g.add_conditional_edges("setup", after_setup,
        {"plan_action": "plan_action", "handle_error": "handle_error"})
    g.add_conditional_edges("plan_action", after_plan,
        {"execute_action": "execute_action", "finalize": "finalize",
         "force_finalize": "force_finalize", "handle_error": "handle_error",
         "plan_action": "plan_action"})
    g.add_conditional_edges("execute_action", after_execute,
        {"plan_action": "plan_action", "force_finalize": "force_finalize", "handle_error": "handle_error"})
    g.add_edge("finalize", END)
    g.add_edge("force_finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()

agentic_ai = _build_graph()
```

`src/graph/runner.py` `run_agent(question, dataset_ids, session_id, ..., run_clarification=False)` creates the `query_runs` row (`status=running`), runs the pre-flight C26 clarification when `run_clarification=True` (first turn only), invokes `agentic_ai` with `dataset_ids` = ALL candidate datasets (the agent's catalog), persists the result — recording on the run ONLY the datasets the agent actually loaded (`get_loaded_ids`) so the C15 cascade tracks real dependencies — calls `generate_suggestions`, and returns the `/ask` payload.
