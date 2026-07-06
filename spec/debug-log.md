# Debug Log — every gap, error, bug, and fix found while building

> **This is a RUNNING log.** Append a new entry at the TOP of the "Log" section every time a
> bug/error/drift is diagnosed (whether or not it ends in a code change — investigations that
> conclude "not a defect" get logged too, so the next person doesn't re-diagnose them).
> Seeded 2026-07-07 by compiling the full git history (`fix`/`sync`/`cleanup` commits carry
> root causes per this repo's commit convention), `spec/parity-gaps.md` (the 2026-06-29 parity
> audit), and the live debugging sessions of 2026-07-01 → 2026-07-07.
>
> **Entry template:**
>
> ```text
> ### YYYY-MM-DD — <one-line title> (<commit SHA | "no code change">)
> - **Symptom:** what was observed.
> - **Root cause:** the actual mechanism.
> - **Fix:** what changed (files) + the regression test, or why no change was needed.
> ```
>
> Related docs: `spec/parity-gaps.md` (point-in-time parity audit vs. the reference build A —
> its open items are mirrored under "Open items" below and tracked here going forward).

---

## Open items / known sharp edges (not yet fixed)

> **All items below were promoted to the roadmap backlog on 2026-07-07** — scheduling, priority
> tiers, and effort estimates live in `spec/roadmap.md` → Future/Backlog (session-cache mutation
> isolation, run-registry release hardening, the parity-gap closure cluster, and real-key
> test-suite pacing). This list remains the technical record of each hazard; when one ships,
> move it into the Log section above with its fix entry.

- **Session DataFrame cache is mutable-shared across turns.** `_session_cache` hands every turn
  the SAME frame object, so in-place mutations by the model (e.g. `df1['Date'] =
  pd.to_datetime(df1['Date'])`) persist for the whole session and change dtypes for later turns.
  Discovered 2026-07-06 while diagnosing the chart-drop bug (it was the mechanism that put
  Timestamps into a run that never called `to_datetime` itself). Downstream symptom fixed
  (`90b9dba`); the shared-mutation behavior itself is unaddressed — a future fix could hand out
  copies or snapshot dtypes, at a memory cost.
- **`_dataframes`/`_loaded_ids`/`_derived_created` leak on an uncaught node exception.** The
  registries are released in `finalize`/`force_finalize`/`handle_error`, but an unanticipated
  exception inside a node propagates out of `graph.invoke()` with no `try/finally`, skipping
  release for that run_id (process-lifetime leak). Pre-existing; more consequential now that the
  persisted eval namespace (4daef94) lives in the same bundle. Known, unfixed.
- **Parity-gaps: only ONE sliver still open** (corrected 2026-07-07 — the original entry here
  copied five gaps from the stale 2026-06-29 audit without re-verifying; see the Log entry of
  2026-07-07 "Backlog seeded from stale parity audit"). Verified against HEAD: C9, C14, C16, and
  C13+C17 are all SHIPPED, and C11's JSON half was fixed by D9. Remaining: **TXT delimiter
  sniffing** — `.txt` uploads are hardcoded `sep="\t"` in `src/api/upload.py` `_parse_dataframe`,
  so comma/pipe-delimited `.txt` files misparse to a single column.
- **Free-tier Gemini key: 15 req/min AND 500 req/day** (updated 2026-07-07). The per-minute
  throttle now self-heals via the provider's adaptive 429 retry (`9dd9fa6` — see Log). The
  DAILY cap does not (retrying is pointless; the retry fail-fasts it by design) — a heavy
  testing day can brick all real-key work until ~midnight Pacific. Empirically confirmed the
  key is SERVED as free tier despite the account having paid billing (both quota IDs say
  `FreeTier`): the key's project isn't linked to billing. Fix in AI Studio (link project to
  billing, or mint a key under the billed project) — lifts both caps. Pending: one live
  re-verification of the retry→success path (un-paced full suite) after quota reset.
- **`ERDiagramPanel.tsx:550`** — pre-existing `react-hooks/exhaustive-deps` lint warning
  (`viewSize` missing from a `useMemo`). Style-tier; fold into the next edit of that file.

---

## Log (newest first)

### 2026-07-07 — 429 storms in test gates: fixed adaptively; daily-cap discovered (9dd9fa6)

- **Symptom:** every back-to-back real-key suite run since 2026-07-06 produced 11–12 spurious
  `429 RESOURCE_EXHAUSTED` failures needing manual paced reruns; the user believed the key was
  paid tier.
- **Root cause(s):** (1) the key is SERVED as free tier despite paid billing on the account —
  burst-tested empirically: exactly 15 rapid calls OK, 16th throttled with quotaId
  `...FreeTier`; the key's Google Cloud project isn't linked to the billing account. (2) The
  app had no 429 handling anywhere — a throttle mid-ReAct-loop failed the whole run.
- **Fix:** adaptive retry in `GeminiProvider` — engages ONLY on an actual 429 (zero cost
  otherwise), honors the server's suggested `retryDelay` (+0.5s) with 2/8/30s fallback, ≤3
  retries, 90s total ceiling that fail-fasts a genuinely exhausted key. 6 offline tests with
  real SDK error shapes. Unit suite 318 green.
- **Live gate finding (new fact):** the verification run was blocked by a SECOND, previously
  unknown quota — the free tier's **500-requests/DAY cap**, exhausted by the day's own gate
  runs. The retry's ceiling fail-fast handled it exactly as designed (observed live 25×), but
  retry→success under per-minute throttle remains unit-test-proven only until a post-reset
  re-run. Lesson: heavy same-day gate activity is itself a quota consumer — budget it, and fix
  the billing linkage.

### 2026-07-07 — Backlog seeded from stale parity audit without re-verification (corrected same day)

- **Symptom:** the newly-promoted "parity-gap closure cluster" backlog item claimed five open
  gaps (C9/C11/C13+C17/C14/C16, ~5–6.5 hrs of work); the user challenged it — most were already
  built.
- **Root cause:** the debug-log seed and the backlog promotion copied `spec/parity-gaps.md`
  (a 2026-06-29 point-in-time audit) verbatim, ignoring that doc's OWN Step-0 warning to
  re-verify each item against current HEAD before acting on it.
- **Fix:** verified each against code — C9 (bulk session select), C14 (multi-dataset e2e test),
  C16 (notes file), C13+C17 (folder drop + staged queue) all shipped; C11's JSON half fixed by
  D9. The backlog item shrank to one Tier-3 sliver: TXT delimiter sniffing (~30–45 min).
  `spec/parity-gaps.md` check-states updated to match. Lesson (same as the 9f926c2 entry):
  audits and audit-derived docs go stale — re-verify against HEAD before promoting them into
  plans, especially when the source doc explicitly says to.

### 2026-07-07 — Ordinary variables vanished between ReAct steps (4daef94)

- **Symptom:** the model assigns `ccl_data = df1[...]` in step 1; step 2 referencing it fails
  `NameError: name 'ccl_data' is not defined` — every occurrence costs a wasted iteration while
  the model re-derives the variable. Observed live in both CCL chart runs on 2026-07-06.
- **Root cause:** `execute_action` built a brand-new `_LazyNamespace` every iteration
  (`build_lazy_namespace(...)` at nodes.py:742); `eval_expression` mutated it in place but the
  dict was a local, discarded on return. Only `frames` (loaded datasets) and `derived_frames`
  (`save_dataset` outputs) had backing stores in `_dataframes[run_id]`. This was originally
  DOCUMENTED as intentional (spec/agent.md, plan_action.md told the model to use `save_dataset`
  to survive to the next step).
- **Fix:** namespace built once per run, cached as `bundle["namespace"]`, reused by identity;
  only the per-call closures (`save_dataset`, `echart`) rebound each iteration. Released for free
  by the existing `_release_dataframe`. Three artifacts rewritten in lockstep (spec/agent.md,
  spec/capabilities/derived-datasets.md, src/prompts/plan_action.md) — `save_dataset`'s remaining
  purpose (outlive the RUN: lineage, Database tab, cross-turn reuse) kept explicit. New test
  `test_ordinary_variable_persists_across_dependent_steps` (scripted 2-dependent-step fake LLM —
  the stock stub finalizes after one action and can never exercise this). 312 unit / 29 real-key.

### 2026-07-06 — Charts with datetime axes silently dropped (90b9dba)

- **Symptom:** "show me some charts" runs completed with chart-describing text but zero rendered
  charts; the model's transcript showed `[chart captured]` on every echart step; one follow-up
  run burned to the 12-iteration cap remaking the same chart nine times.
- **Root cause:** `_as_jsonable` (sandbox.py) coerced numpy ints/floats/NaN but NOT
  datetime-likes. A `pd.Timestamp` x-axis made `json.dumps(option)` raise
  `TypeError: Object of type Timestamp is not JSON serializable` at the capture site
  (nodes.py:785), caught + logged (`chart_serialize_failed`) + chart discarded — while the step
  result still read `[chart captured]`, so the chart guardrail (correctly) kept rejecting finals,
  compounding the cost. Trigger was data-shape-dependent, not a regression: an early turn's
  in-place `pd.to_datetime` on the session-cached frame put Timestamps into all later turns.
  Bonus latent bug found during the fix: `np.timedelta64` subclasses `np.signedinteger`, so
  timedeltas were silently charted as bare ints.
- **Fix:** two layers — `_as_jsonable` gains datetime/date/np.datetime64→ISO (NaT→null, checked
  BEFORE the datetime branch since `pd.NaT` IS a datetime that isoformats to `'NaT'`;
  np.timedelta64 branch moved BEFORE np.integer), and the capture-site dumps uses `default=str`
  so any future exotic value degrades to a string instead of vaporizing the chart. 10 regression
  tests incl. a nodes-level `pd.Interval` degrade test. Real-Gemini chart e2e green.
  Spec follow-up `5417e2e` documented the guarantee + fixed the imprecise "serialisation failure
  → step error" wording (a capture failure is a step error; a serialization failure only logs).

### 2026-07-05 — ERD zoom always anchored top-left; no card drag; undocumented interactions (0f6c261 / 4195a3b)

- **Symptom:** wheel-zoom in the ER diagram zoomed toward the origin instead of the cursor;
  cards couldn't be repositioned; after building both, the interactions were undocumented drift.
- **Root cause (zoom):** pan wasn't compensated for the scale change — correct form is
  `panNew = anchor − (zNew/zOld)·(anchor − panOld)` for the `translate(pan) scale(zoom)` order,
  applied via nested state updaters to avoid stale closures under rapid wheel events.
- **Fix:** anchor-preserving zoom (cursor for wheel, viewport-center for buttons), session-only
  per-card drag with a 3px click-suppression threshold, Reset-layout button, pure-black dark-mode
  canvas (`.erd-canvas` override, equal-specificity-later-in-source pattern). Logic extracted to
  `erdInteraction.ts` with 9 node tests. Drift closed by extending `spec/ui.md:43`.

### 2026-07-03 — resync's documented response shape overstated (9f926c2, then 40f21c5)

- **Symptom:** none live — caught by the post-Phase-9 drift audit. `spec/api.md` + the `api.ts`
  type claimed `POST /connections/{id}/resync` returns the full `GET /datasets/{id}` detail
  shape; it actually returns `_list_item`'s smaller shape (deliberately mirroring `/re-derive`).
- **Root cause:** spec wording overstated the contract; harmless today only because the sole
  caller discards the body and re-fetches.
- **Fix:** spec + TS type corrected (spec-wins direction inverted deliberately with user
  approval — the CODE matched the sibling-endpoint precedent). The fix commit itself then
  omitted `format` from the field enumeration — caught by re-audit, closed in `40f21c5`.
  Lesson: audit the fix commit too.

### 2026-07-03 — `agent.py --run` segfaults on Windows after adding a native dep (3383f9f)

- **Symptom:** launcher hard-crashed once `psycopg2-binary` entered the venv.
- **Root cause:** `os.execvpe` process-replacement through uv's launcher — the identical uvicorn
  command ran fine as a plain subprocess; the crash was specific to exec semantics, not the app.
- **Fix:** `subprocess.run` + `sys.exit(returncode)`. Companion earlier Windows fix `4763a38`:
  UTF-8 stdout reconfigure (status glyphs crashed non-console stdout) + shell-spawn for `.cmd`
  shims (pnpm/node).

### 2026-07-03 — resync dead code re-set provenance fields it already had (d559752)

- **Symptom:** none — Low finding from the Phase 9 drift audit: `connections_resync` re-assigned
  `source_type`/`source_uri_display`/`source_table_name` onto a dict that already contained them,
  under a stale comment claiming `_list_item` lacked them (true only before the follow-up fix).
- **Fix:** dead lines + stale comment removed; response relies purely on `_list_item`.

### 2026-07-02 — Fast Mode badge vanished on session reload (efaf1cd sync)

- **Symptom:** the "⚡ Fast Mode" badge on an answer disappeared after reload/resume even though
  the run genuinely ran under Fast Mode.
- **Root cause:** `fast_mode` was request-scoped only (spec'd "never persisted"); the badge read
  `AskResponse.fast_mode` (live echo), but `GET /sessions/{id}`'s `_turn_payload` had no such
  field — `QueryRunRow` had no column.
- **Fix:** `query_runs.fast_mode` column (+ migration `a1b2c3d4e5f6`), set once at row creation,
  returned per turn; spec amended (fast-mode.md "Persistence Amendment", data.md, api.md).
  Same sync closed stale "six components" wording in spec/agent.md + spec/data.md and the
  broken `prompt_breakdown.dataset_notes > 0` success criterion in dataset-context-notes.md.

### 2026-07-02 — C29 dataset_notes bucket was always 0 (b3388d4)

- **Symptom:** the token-breakdown widget's "Dataset notes" bar never moved.
- **Root cause:** `setup` folds dataset notes into the catalog line, which is measured as
  `dataset_schemas` — the sixth bucket was a dead line item by construction.
- **Fix:** dropped end-to-end (runner/nodes/widget/spec, 6→5 components) with a regression
  guard asserting the key's ABSENCE.

### 2026-07-02 — Global memory injected additively and unbounded (2ee0bb5)

- **Symptom:** `memory` was the largest variable bucket in a real breakdown (30% / 4,693 tokens),
  re-sent byte-identical every ReAct iteration.
- **Root cause:** two independent defects in `src/graph/memory.py`: (1) `get_memory_block()` sent
  the raw `global_memory` text PLUS the ≤20 compressed C31 facts distilled FROM it — compression
  made the block strictly LARGER; (2) `PATCH /memory` accepted any-length text (dataset notes are
  capped at 4000; memory wasn't).
- **Fix:** facts-only injection when facts exist, raw-text fallback when they don't (offline/stub
  compression yields `[]` — memory must never silently drop); 4000-char cap with a 400 mirroring
  `PATCH /datasets/{id}/context`; live counter in the memory modal. Real-Gemini test asserts the
  injected block contains the facts and NOT the raw text.

### 2026-07-02 — Dark-mode contrast + toggle-visibility fixes (6126224, 98585e0, 94d280a, b2edc94)

- **Symptom (cluster):** native widgets (selects, scrollbars) rendered light-scheme in dark mode;
  hover states and blue chips had illegible contrast; the Fast Mode toggle was a faint small chip
  users didn't notice; sidebar chevrons pointed the wrong way.
- **Root cause:** the theming remap (Phase 7) covers Tailwind utility classes — native-widget
  `color-scheme`, pseudo-class hover variants, and one-off component styles each needed their own
  override; the toggle followed the small-chip family sizing when it needed standalone-control
  prominence.
- **Fix:** `color-scheme` + select styling, per-variant hover overrides, full-size toggle.

### 2026-07-01 — Session cache served deleted datasets (53d062d, closes parity-gap C27)

- **Symptom:** after deleting a dataset mid-session, the next query could still read its stale
  in-memory frame.
- **Root cause:** `_delete_one()`/`delete_all_datasets()` removed the DB row + files but never
  called `invalidate_dataset_cache` (clean/apply and re-derive already did).
- **Fix:** invalidation on single delete (incl. cascade-deleted derived children) and delete-all;
  red-before/green-after tests in `test_datasets_delete_cache.py`.

### 2026-07-01 — Clarification card persisted/re-fired across the thread (ccca306)

- **Symptom:** an old mid-thread clarification came back as an ACTIVE prompt on reload, and
  clicking it could re-fire its original trigger question.
- **Root cause:** the card had no notion of being superseded — it rendered live regardless of
  whether it was the newest turn.
- **Fix:** `resolved` prop → inert "✓ Resolved" note unless it is the latest turn.

### 2026-07-01 — Raw uncompressed notes leaked into prompts via async self-heal (8e98bbf)

- **Symptom:** when C31 facts weren't ready, raw (potentially 4000-char) notes were sent to the
  LLM while a background compression "self-healed"; also `/ask`'s `datasets_used` showed raw
  UUIDs in the UI.
- **Fix:** synchronous on-demand compression — raw notes are NEVER passed (empty string if
  compression yields nothing); `datasets_used` resolves ids → filenames. Test asserts raw notes
  never reach the prompt.

### 2026-07-01 — Chart requests sometimes finalized with no chart (29b4b52)

- **Symptom:** "…with charts" questions inconsistently produced no chart — the model finalized
  with a table instead of calling `echart()`.
- **Fix (two-part):** prompt mandate in plan_action.md + a deterministic graph guardrail —
  `wants_chart` regex at setup, a "chart is REQUIRED" reminder while unmet, `after_plan` forcing
  extra plan iterations (`chart_force_count` capped so stub mode still terminates). Verified 5/5
  real-Gemini runs. (This guardrail is also what amplified the 2026-07-06 serialization bug —
  guardrails that retry on a symptom compound whatever silently causes the symptom.)

### 2026-06-30 — C29 breakdown never added up (df62d5c → 503e5b2)

- **Symptom:** breakdown bars didn't sum to the total; the total (cumulative across iterations)
  never matched the single-snapshot component estimates; ~87% of the prompt (the system template)
  was unaccounted.
- **Root cause:** components were single-call chars/4 estimates excluding the system template,
  displayed against REAL cumulative provider token counts.
- **Fix:** measured per-bucket char partition of the WHOLE prompt, accumulated per-iteration,
  scaled to the real cumulative `tokens_input` so components sum EXACTLY; output row added.
  Along the way: an autouse conftest fixture resetting process-global node registries killed an
  intermittent stub-test flake (shared module state across tests — same class of problem as the
  session-cache sharp edge above).

### 2026-06-30 — "Last query (In/Out)" blanked on reload (4b7b206)

- **Symptom:** the token row showed "— / —" for persisted runs while the context-window bar
  (with a persisted fallback) showed real values.
- **Root cause:** the row read only the ephemeral in-memory prop, null after reload.
- **Fix:** `/stats/daily` exposes `last_tokens_input/output`; widget falls back to them.

### 2026-06-30 — Initial spec↔code drift sweep on the fresh fork (e8bce83)

- **Symptom (cluster):** `AGENT_MAX_ITERATIONS` default disagreed across spec/env/tests (6 vs 12);
  `SessionTurn` lacked `charts`/`duration_ms`; `POST /runs/{id}/cancel` untested; stale migration
  revision hardcoded in the roadmap gate; `force_finalize` missing from the documented edge map.
- **Fix:** aligned to 12, model fields added, cancel test added, spec docs corrected. First
  demonstration of the drift-audit loop this log now feeds on.

### 2026-06-29 — Parity audit vs. reference build A (`spec/parity-gaps.md`, no single commit)

- 30 capabilities audited: 24 at parity or ahead, 6 gaps. Closed since: C31 (compression wired,
  2026-06-29), C27 (cache invalidation, `53d062d`), C29 + C8 (verified already shipped,
  2026-07-01), C10 (filename-dup, 2026-06-29). Still open: C11, C14, C9, C16 (re-verify), C13+C17
  — mirrored in "Open items" above.

---

## Investigations that ended in "no code change"

### 2026-07-06 — "Pre-flight clarification stopped appearing" (no code change)

- **Reported:** vague questions ("Describe", "Show me some charts") no longer produced a
  clarification turn.
- **Investigated:** `tests/integration/test_preflight_real.py` passed 3/3 against the real key
  (after the user rotated an expired/limited API key — the first run's failures were quota/key
  noise). Behavioral notes that explain most "missing" clarifications by design: C26 runs ONLY on
  the FIRST turn of a conversation (`run_clarification=True` nowhere else), is suppressed
  entirely by Fast Mode, and is a model judgment call on genuinely vague first turns — mid-session
  vague questions never trigger it. Logged so the next report starts from these constraints.

### 2026-07-06 — Full-suite 429 storms are not regressions (protocol, no code change)

- 11–12 integration/e2e failures appearing in every back-to-back full-suite run, all
  `429 RESOURCE_EXHAUSTED` (free tier, 15 req/min), all green on isolated rerun. Standing
  protocol documented in "Open items". A paid-tier key or a paced test runner would retire this.

---

## Build/tooling incidents (not product bugs, worth remembering)

- **2026-07-03 — qa-auditor downgraded the LIVE dev DB during a migration check** (alembic `-x`
  URL override isn't wired in `alembic/env.py`, so its scratch-DB attempt hit `data/agent.db`).
  Caught immediately, restored from a pre-test backup, schema + row count verified. Rule since:
  migration round-trip tests run against a disposable copy via `AGENT_DATABASE_URL`, never the
  live file.
- **2026-06-30 — intermittent stub-test flake from process-global registries** (fixed by the
  autouse reset fixture in `df62d5c`) — module-level mutable state and tests don't mix without
  explicit resets.
- **Windows launcher quirks** (`4763a38`, `3383f9f`): non-console stdout can't take unicode
  glyphs without an explicit UTF-8 reconfigure; `.cmd` shims need shell spawn; `os.execvpe`
  through uv's launcher segfaults once native deps are present — use `subprocess.run`.
