/**
 * API helper for the Data Analysis Agent frontend.
 *
 * The backend (FastAPI) is served single-origin: the UI lives under `/app/`,
 * the API at the origin root. All fetches here use ROOT-RELATIVE paths
 * (e.g. "/health", "/upload") which resolve to the origin root regardless of
 * the `/app` basePath — so the same build works in dev and in the bundled
 * single-origin server.
 *
 * Envelope contract (spec/api.md):
 *   success: { "data": <payload>, "error": null }   (HTTP 2xx)
 *   error:   { "detail": { "code": <str>, "message": <str> } }   (HTTP 4xx/5xx)
 *
 * `unwrap()` returns the success payload and throws an `ApiError` carrying the
 * `code` + `message` on the error shape, so callers can branch on
 * `err.code === "duplicate_dataset"` etc.
 */

/** Error thrown for any non-2xx response, carrying the contract's code/message. */
export class ApiError extends Error {
  code: string
  status: number
  /** The raw `detail` object (may carry extra fields like `existing_*`). */
  detail: Record<string, unknown> | null

  constructor(
    code: string,
    message: string,
    status: number,
    detail: Record<string, unknown> | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.detail = detail
  }
}

/** Parse a fetch Response per the envelope contract; throw ApiError on failure. */
async function unwrap<T>(res: Response): Promise<T> {
  let body: unknown = null
  const text = await res.text()
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      // Non-JSON body (e.g. a proxy error page) — fall through to a generic error.
      body = null
    }
  }

  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? (body as { detail: unknown }).detail
        : null

    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>
      const code = typeof d.code === 'string' ? d.code : 'error'
      const message =
        typeof d.message === 'string' ? d.message : `Request failed (${res.status})`
      throw new ApiError(code, message, res.status, d)
    }

    // Fallback when the error body isn't in the documented shape.
    const message =
      typeof detail === 'string' ? detail : `Request failed (${res.status})`
    throw new ApiError('error', message, res.status, null)
  }

  // Success: unwrap { data, error } when present, else return the raw body.
  if (body && typeof body === 'object' && 'data' in body) {
    return (body as { data: T }).data
  }
  return body as T
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'GET', headers: { Accept: 'application/json' } })
  return unwrap<T>(res)
}

async function postJson<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  return unwrap<T>(res)
}

async function patchJson<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<T>(res)
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'DELETE', headers: { Accept: 'application/json' } })
  return unwrap<T>(res)
}

async function delJson<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<T>(res)
}

// ---------------------------------------------------------------------------
// Response types (subset of spec/api.md needed in Phase 2)
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string
  provider: string
  /** The model id the active provider will actually call (may be "" in stub). */
  model?: string
}

export interface UploadResponse {
  dataset_id: string
  filename: string
  format: string
  row_count: number
  col_count: number
  columns: string[]
  context: string | null
  auto_notes_status: string | null
}

// ---------------------------------------------------------------------------
// Multi-sheet Excel import (C38, Phase 12)
// ---------------------------------------------------------------------------

/** One sheet enumerated by the `type:"multi_sheet"` inspect response (workbook order). */
export interface SheetInfo {
  sheet_name: string
  row_count: number
  col_count: number
  /** True when the sheet has 0 rows or 0 cols — listed so the picker can render it disabled. */
  empty: boolean
}

/**
 * POST /upload inspect variant (spec/api.md): an `.xlsx`/`.xls` workbook with
 * ≥2 non-empty sheets registers NOTHING — the raw bytes are stashed server-side
 * (in-memory, 15-min TTL) and this response carries the staging token + per-sheet
 * metadata so the client can import chosen sheets via POST /upload/sheets.
 * A single-sheet workbook returns the plain `UploadResponse` (no `type` key).
 */
export interface MultiSheetUploadResponse {
  type: 'multi_sheet'
  staging_token: string
  filename: string
  sheets: SheetInfo[]
  /** The C16-resolved workbook-level notes that imported sheets will inherit. */
  context: string | null
  expires_in_seconds: number
}

/** Union returned by `api.upload` — branch with {@link isMultiSheetUpload}. */
export type UploadResult = UploadResponse | MultiSheetUploadResponse

/** Type guard: the multi-sheet inspect variant is distinguished by its `type` key. */
export function isMultiSheetUpload(result: UploadResult): result is MultiSheetUploadResponse {
  return 'type' in result && result.type === 'multi_sheet'
}

/** One requested sheet in the POST /upload/sheets body. */
export interface SheetImportRequest {
  sheet_name: string
  /** Optional per-sheet notes override; omitted ⇒ the sheet inherits the workbook-level context. */
  context?: string
}

/**
 * Per-sheet outcome of POST /upload/sheets (C36 per-item precedent — one
 * sheet's failure never aborts the others; the call itself stays 200):
 *  - `ok`        → `dataset` carries the single-upload response shape
 *  - `duplicate` → C10 fields (`match_type`, `existing_*`) as a per-sheet
 *                  result, not an HTTP 409 — retry just that sheet with force
 *  - `error`     → `message` only (empty sheet, unknown name, parse/disk failure)
 */
export interface SheetImportResult {
  sheet_name: string
  status: 'ok' | 'duplicate' | 'error'
  dataset?: UploadResponse
  match_type?: 'content' | 'content_and_name' | 'name'
  existing_dataset_id?: string
  existing_filename?: string
  message?: string
}

/** POST /upload/sheets response — 200 even if every sheet failed. */
export interface SheetsImportResponse {
  filename: string
  results: SheetImportResult[]
}

export interface DatasetSummary {
  id: string
  filename: string
  row_count: number
  col_count: number
  format: string
  /** `uploaded` | `derived` | `connected` (C36). */
  origin: string
  /** A derived dataset whose parent changed after derivation (C25). */
  stale?: boolean
  /** Lineage: parent dataset ids this derived set was built from (C25). */
  derived_from_dataset_ids?: string[] | null
  /** The run that produced this derived dataset. */
  derived_from_run_id?: string | null
  /** Plain-language summary of how a derived dataset was produced. */
  derivation_description?: string | null
  /** C36/C38 — source data type: connector name (e.g. "postgresql") for connected datasets, "excel" for Excel imports; null unless origin="connected" or "uploaded". */
  source_type?: string | null
  /** C36/C38 — credential-free source identifier: connection URI for connected datasets, file path for Excel imports; null unless origin="connected" or "uploaded". */
  source_uri_display?: string | null
  /** C36/C38 — source table or sheet name; null unless origin="connected" or "uploaded". */
  source_table_name?: string | null
  [key: string]: unknown
}

export interface ColumnSchema {
  name: string
  dtype: string
}

export interface DatasetDetail extends DatasetSummary {
  columns_schema: ColumnSchema[]
  context: string | null
  /** The pandas code that produced a derived dataset (C25 re-derive). */
  derivation_code: string | null
  /** C30 notes generation state: `pending` | `done` | `failed` | null. */
  auto_notes_status: string | null
  /** C31 compressed facts (≤20) extracted from the context notes. */
  context_facts?: string[] | null
}

/** POST /datasets/{id}/re-derive (C25) — re-run derivation vs current parents. */
export interface ReDeriveResponse {
  dataset_id: string
  stale: boolean
  row_count: number
  col_count: number
  [key: string]: unknown
}

/**
 * POST /datasets/{id}/clean (C24) — NL cleaning PREVIEW. The server runs the
 * generated pandas on a COPY and returns the code + before/after counts +
 * sample previews; it never mutates the dataset.
 */
export interface CleanPreviewResponse {
  code: string
  before_row_count: number
  after_row_count: number
  before_col_count: number
  after_col_count: number
  /** A few sample rows before/after the clean, mirroring /preview's shape. */
  before_preview?: PreviewResponse | null
  after_preview?: PreviewResponse | null
  [key: string]: unknown
}

/** POST /datasets/{id}/clean/apply (C24) — applied result (updated counts). */
export interface CleanApplyResponse {
  dataset_id: string
  row_count: number
  col_count: number
  [key: string]: unknown
}

/** POST /datasets/{id}/describe (C30) — trigger; returns the pending status. */
export interface DescribeResponse {
  dataset_id: string
  auto_notes_status: string
  [key: string]: unknown
}

export interface PreviewResponse {
  columns: string[]
  rows: unknown[][]
}

export interface AskStep {
  action: string
  result: string
  is_error: boolean
  reasoning?: string
}

/**
 * Response from POST /ask. Two variants share this shape (spec/api.md):
 *  - `type: "answer"`       — the full analysis result (answer + steps + tokens…)
 *  - `type: "clarification"`— a thin pre-flight (C26) result carrying
 *    `clarification_question`, `run_id`, `session_id`, and (C37) up to 3
 *    refined candidate questions in `suggested_questions`; the answer/steps
 *    fields are absent, so they are typed optional here.
 */
export interface AskResponse {
  type: string
  run_id: string
  session_id?: string | null
  dataset_ids?: string[]
  derived_dataset_ids?: string[]
  datasets_used?: string[]
  selector_reasoning?: string | null
  answer_markdown?: string
  answer_html?: string
  iteration_count?: number
  tokens_input?: number
  tokens_output?: number
  status?: string
  is_best_effort?: boolean
  steps?: AskStep[]
  /**
   * Follow-up questions on a `type:"answer"` turn, OR — C37 — up to 3 refined
   * candidate questions on a `type:"clarification"` turn (produced by the SAME
   * single pre-flight call; `[]` when the model offered none or its reply fell
   * back to plain-text parsing). Live-only either way: resumed turns report `[]`.
   */
  suggested_questions?: string[]
  prompt_breakdown?: Record<string, unknown>
  /** Inline ECharts option objects captured during analysis, each a JSON string (C4). */
  charts?: string[]
  /** Wall-clock response time of the run in milliseconds (answer path). */
  duration_ms?: number
  /** C35 — whether this run applied Fast Mode (tighter cap, no clarification/suggestions). */
  fast_mode?: boolean
  // Clarification variant (type === "clarification"):
  clarification_question?: string
}

/**
 * Arguments for the `ask` wrapper. There is NO dataset scoping: selection is
 * agent-driven server-side (the agent picks from a catalog of all datasets).
 */
export interface AskArgs {
  question: string
  /** Continue an existing session; omit to start a new one server-side. */
  sessionId?: string | null
  /** Skip the C26 clarification pre-flight (used on clarification re-submit). */
  skipClarification?: boolean
  /**
   * C35 — per-query Fast Mode: tighter iteration cap (5), skips pre-flight
   * clarification and follow-up suggestions, truncates action_history results,
   * adds a brevity instruction, and disables the forced-chart retry. Default
   * `false`. Never persisted — a per-request flag only (spec/capabilities/fast-mode.md).
   */
  fastMode?: boolean
  /** Abort signal so the UI can cancel the request (the Stop button). */
  signal?: AbortSignal
}

export interface CurrentRun {
  run_id: string | null
  status: string
  iteration_count: number
  max_iterations: number
}

/** GET /stats/daily — today's aggregated usage (spec/api.md). */
export interface DailyStats {
  date: string
  model: string
  tokens_input: number
  tokens_output: number
  query_count: number
  context_limit: number
  /** Input tokens of the most recent run today — the last query's prompt size. */
  last_prompt_tokens?: number
  /** Clearer alias for the most recent run's input tokens. */
  last_tokens_input?: number
  /** Output tokens of the most recent run today — for the persisted "Last query (In/Out)" fallback. */
  last_tokens_output?: number
}

// ---------------------------------------------------------------------------
// Session types (Phase 3)
// ---------------------------------------------------------------------------

/** A session summary as returned by GET /sessions and /datasets/{id}/sessions. */
export interface Session {
  id: string
  name: string | null
  dataset_id?: string | null
  dataset_ids?: string[]
  turn_count: number
  first_question: string | null
  created_at?: string | null
  updated_at?: string | null
  [key: string]: unknown
}

/** One turn within a session (GET /sessions/{id} → turns[]). Mirrors /ask. */
export interface TurnView {
  run_id: string
  question: string
  answer_markdown?: string | null
  answer_html?: string | null
  type?: string
  clarification_question?: string | null
  iteration_count?: number
  tokens_input?: number
  tokens_output?: number
  status?: string
  is_best_effort?: boolean
  steps?: AskStep[]
  suggested_questions?: string[]
  dataset_ids?: string[]
  datasets_used?: string[]
  selector_reasoning?: string | null
  prompt_breakdown?: Record<string, unknown>
  /** Inline ECharts option objects (JSON strings) captured for this turn (C4). */
  charts?: string[]
  created_at?: string | null
  /** Approximate response time (ms) derived from the run's lifespan. */
  duration_ms?: number
  /** C35 — whether this turn ran under Fast Mode. */
  fast_mode?: boolean
  [key: string]: unknown
}

/** Full session detail with its turns (GET /sessions/{id}). */
export interface SessionDetail extends Session {
  turns: TurnView[]
}

// ---------------------------------------------------------------------------
// Memory types (Phase 3 — C29/C31)
// ---------------------------------------------------------------------------

export interface MemoryResponse {
  global_memory: string
  global_memory_facts: string[]
}

// ---------------------------------------------------------------------------
// Settings (D4)
// ---------------------------------------------------------------------------

export interface SettingsData {
  llm_model: string | null
  max_iterations: string | null
  price_input_per_million: string | null
  price_output_per_million: string | null
}

// ---------------------------------------------------------------------------
// External database connectors (C36, Phase 9, BETA)
// ---------------------------------------------------------------------------

/** GET /connections/status — whether AGENT_ENABLE_DB_CONNECTORS is on. */
export interface ConnectionsStatusResponse {
  enabled: boolean
}

/** One column in a discovered table's schema (POST /connections/check). */
export interface ConnectorColumnSchema {
  name: string
  dtype: string
  nullable: boolean
}

/** One table discovered by POST /connections/check. `row_count` is always null. */
export interface ConnectorTableInfo {
  table_name: string
  column_names: string[]
  schema: ConnectorColumnSchema[]
  row_count: number | null
}

/** A best-effort foreign-key relationship discovered by POST /connections/check. */
export interface ConnectorRelationship {
  from_table: string
  from_column: string
  to_table: string
  to_column: string
}

/** Body for POST /connections/check and (minus `tables`) POST /connections/import. */
export interface ConnectionCheckRequest {
  /** Only "postgresql" ships in this phase. */
  type: string
  /** Full connection string incl. credentials — never persisted client-side beyond submitting the request. */
  uri: string
}

export interface ConnectionCheckResponse {
  tables: ConnectorTableInfo[]
  relationships: ConnectorRelationship[]
}

/** One table the user chose to import, as sent in POST /connections/import. */
export interface ConnectionImportTableRequest {
  table_name: string
  alias?: string
  filter?: string
}

export interface ConnectionImportRequest {
  type: string
  uri: string
  tables: ConnectionImportTableRequest[]
}

/** Per-table outcome of POST /connections/import — one table's failure never aborts the others. */
export interface ConnectionImportResult {
  table_name: string
  status: 'ok' | 'error'
  dataset_id?: string
  message?: string
}

export interface ConnectionImportResponse {
  results: ConnectionImportResult[]
}

// ---------------------------------------------------------------------------
// Suggested questions (C37, Phase 10)
// ---------------------------------------------------------------------------

/** GET /suggestions/starters — session-start "Try asking:" questions (spec/api.md). */
export interface StarterSuggestionsResponse {
  /**
   * 0–3 starter questions built from a metadata-only catalog of ALL workspace
   * datasets. `[]` on an empty workspace, any LLM failure, or the offline stub
   * — the UI hides the block on an empty list.
   */
  questions: string[]
}

// ---------------------------------------------------------------------------
// Endpoint wrappers (Phase 2 surface)
// ---------------------------------------------------------------------------

export const api = {
  health: () => getJson<HealthResponse>('/health'),

  /**
   * POST /upload — multipart `file`, optional `context`, optional `?force=true`.
   * On a duplicate the server returns 409 with code `duplicate_dataset`; this
   * surfaces as an `ApiError` the caller can branch on.
   *
   * C38: an `.xlsx`/`.xls` workbook with ≥2 non-empty sheets returns the
   * `type:"multi_sheet"` inspect variant instead of registering a dataset —
   * branch with `isMultiSheetUpload(result)` and follow up with
   * `api.uploadSheets(...)`. Single-sheet workbooks and every other format
   * return the plain `UploadResponse` exactly as before.
   */
  async upload(
    file: File,
    opts: { context?: string; force?: boolean } = {},
  ): Promise<UploadResult> {
    const form = new FormData()
    form.append('file', file)
    if (opts.context && opts.context.trim()) {
      form.append('context', opts.context.trim())
    }
    const path = opts.force ? '/upload?force=true' : '/upload'
    const res = await fetch(path, { method: 'POST', body: form })
    return unwrap<UploadResult>(res)
  },

  /**
   * POST /upload/sheets (C38) — import chosen sheets from a staged multi-sheet
   * workbook (the second step after a `type:"multi_sheet"` inspect response).
   * Each sheet is registered independently — inspect the per-sheet `results`
   * (`ok` / `duplicate` / `error`); the call is 200 even if every sheet failed.
   * Whole-call failures: 404 `staging_expired` (token unknown/expired — re-drop
   * the file) and 400 `empty_selection`. The token is NOT consumed — more
   * sheets can be imported from it until the 15-min TTL expires.
   */
  uploadSheets: (payload: {
    staging_token: string
    sheets: SheetImportRequest[]
    /** Bypass the per-sheet duplicate check for all sheets in this call. */
    force?: boolean
  }): Promise<SheetsImportResponse> =>
    postJson<SheetsImportResponse>('/upload/sheets', {
      staging_token: payload.staging_token,
      sheets: payload.sheets,
      force: payload.force ?? false,
    }),

  listDatasets: () => getJson<DatasetSummary[]>('/datasets'),

  getDataset: (id: string) => getJson<DatasetDetail>(`/datasets/${encodeURIComponent(id)}`),

  preview: (id: string, rows = 10) =>
    getJson<PreviewResponse>(`/datasets/${encodeURIComponent(id)}/preview?rows=${rows}`),

  deleteDataset: (id: string) => del<unknown>(`/datasets/${encodeURIComponent(id)}`),

  // --- Datasets: Phase-4 operations (charts / derived / clean / notes) ------

  /** DELETE /datasets — clear the whole data universe (cascade). */
  clearAllDatasets: () => del<unknown>('/datasets'),

  /**
   * POST /datasets/{id}/re-derive (C25) — re-run a derived dataset's
   * `derivation_code` against its current parents and clear its stale flag.
   * 400 `not_derived` / 404 `parent_not_found` / 400 `re_derive_error` surface
   * as `ApiError`s the caller can branch on.
   */
  reDerive: (id: string) =>
    postJson<ReDeriveResponse>(`/datasets/${encodeURIComponent(id)}/re-derive`, {}),

  /**
   * POST /datasets/{id}/clean (C24) — NL cleaning PREVIEW. Sends the user's
   * plain-English `instruction`; the server generates pandas, runs it on a COPY,
   * and returns the code + before/after counts + previews. Never mutates.
   */
  cleanPreview: (id: string, instruction: string) =>
    postJson<CleanPreviewResponse>(`/datasets/${encodeURIComponent(id)}/clean`, {
      instruction,
    }),

  /**
   * POST /datasets/{id}/clean/apply (C24) — apply the cleaning in place. Pass the
   * previewed `code` to apply exactly what was shown (preferred), or fall back to
   * the original `instruction` so the server re-derives the code.
   */
  cleanApply: (id: string, codeOrInstruction: { code?: string; instruction?: string }) =>
    postJson<CleanApplyResponse>(
      `/datasets/${encodeURIComponent(id)}/clean/apply`,
      codeOrInstruction,
    ),

  /**
   * POST /datasets/{id}/describe (C30) — trigger async notes generation. Sets
   * `auto_notes_status=pending`; the caller polls GET /datasets/{id} for the
   * pending → done/failed transition.
   */
  describeDataset: (id: string) =>
    postJson<DescribeResponse>(`/datasets/${encodeURIComponent(id)}/describe`, {}),

  /** PATCH /datasets/{id}/context (C12) — save the dataset's context notes. */
  patchContext: (id: string, context: string) =>
    patchJson<DatasetDetail>(`/datasets/${encodeURIComponent(id)}/context`, { context }),

  /**
   * POST /ask — the analysis entry point (spec/api.md).
   *
   * Body: `{question, session_id?, skip_clarification, fast_mode}`. Dataset
   * selection is agent-driven server-side (the agent picks from a catalog of
   * every dataset), so the body carries no dataset scoping.
   *  - Pass `sessionId` to continue a session; omit to start a new one.
   *  - Pass `skipClarification` to bypass the C26 pre-flight (used when a user
   *    re-submits after a clarification turn).
   *  - Pass `fastMode` to opt into C35 Fast Mode for this request only (default
   *    `false`); the response echoes the `fast_mode` that was actually applied.
   *
   * Returns either a `type:"answer"` or a `type:"clarification"` AskResponse.
   */
  ask: (args: AskArgs) => {
    const body: Record<string, unknown> = {
      question: args.question,
      skip_clarification: args.skipClarification ?? false,
      fast_mode: args.fastMode ?? false,
    }
    if (args.sessionId) body.session_id = args.sessionId
    return postJson<AskResponse>('/ask', body, args.signal)
  },

  currentRun: () => getJson<CurrentRun>('/runs/current'),

  /** Cooperatively cancel an in-flight run (the Stop button). Best-effort. */
  cancelRun: (runId: string) =>
    postJson<{ run_id: string; cancelling: boolean }>(
      `/runs/${encodeURIComponent(runId)}/cancel`,
      {},
    ),

  dailyStats: () => getJson<DailyStats>('/stats/daily'),

  // --- Sessions (Phase 3) ---------------------------------------------------

  listSessions: () => getJson<Session[]>('/sessions'),

  getSession: (id: string) => getJson<SessionDetail>(`/sessions/${encodeURIComponent(id)}`),

  renameSession: (id: string, name: string) =>
    patchJson<Session>(`/sessions/${encodeURIComponent(id)}/name`, { name }),

  deleteSession: (id: string) => del<unknown>(`/sessions/${encodeURIComponent(id)}`),

  deleteAllSessions: () => del<unknown>('/sessions'),

  /**
   * DELETE /sessions (bulk) — delete a specific set of sessions.
   * Body: { session_ids: string[] }. 400 if the list is empty.
   * Sessions with an active run are silently skipped.
   * Returns { deleted: number } — the count actually removed.
   */
  bulkDeleteSessions: (ids: string[]): Promise<{ deleted: number }> =>
    delJson<{ deleted: number }>('/sessions', { session_ids: ids }),

  datasetSessions: (datasetId: string) =>
    getJson<Session[]>(`/datasets/${encodeURIComponent(datasetId)}/sessions`),

  // --- Memory (Phase 3 — C29/C31) ------------------------------------------

  getMemory: () => getJson<MemoryResponse>('/memory'),

  patchMemory: (text: string) =>
    patchJson<MemoryResponse>('/memory', { global_memory: text }),

  // --- Settings (D4) --------------------------------------------------------

  getSettings: () => getJson<SettingsData>('/settings'),

  async patchSettings(patch: Partial<SettingsData>): Promise<SettingsData> {
    const res = await fetch('/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    return unwrap<SettingsData>(res)
  },

  // --- External database connectors (C36, Phase 9, BETA) --------------------

  connections: {
    /** GET /connections/status — always 200, never gated; drives whether the BETA affordance renders at all. */
    status: () => getJson<ConnectionsStatusResponse>('/connections/status'),

    /**
     * POST /connections/check — opens one connection, runs a real connect +
     * `SELECT 1` (8s hard timeout) then table/relationship discovery, and
     * closes it. Nothing is persisted. Never echoes the URI back.
     */
    check: (payload: ConnectionCheckRequest) =>
      postJson<ConnectionCheckResponse>('/connections/check', payload),

    /**
     * POST /connections/import — re-validates the connection, then pulls and
     * registers each requested table independently as an ordinary dataset
     * (`origin="connected"`). One table's failure never aborts the others —
     * see the per-table `status`/`message` in the response.
     */
    import: (payload: ConnectionImportRequest) =>
      postJson<ConnectionImportResponse>('/connections/import', payload),

    /**
     * POST /connections/{dataset_id}/resync — manual re-pull of a connected
     * dataset's source table (mirrors the C25 `/re-derive` pattern). Returns
     * the updated dataset as a `DatasetSummary` (the same list-item shape as
     * an entry in `GET /datasets`) — NOT the fuller `DatasetDetail` shape
     * (no `columns_schema`/`content_hash`/`file_path`/`parquet_path`/
     * `derivation_code`/`context_facts`). Same precedent as `/re-derive`.
     * `source_uri_raw` is never included. Callers needing full detail should
     * follow up with `datasets.get(datasetId)`.
     */
    resync: (datasetId: string) =>
      postJson<DatasetSummary>(`/connections/${encodeURIComponent(datasetId)}/resync`, {}),
  },

  // --- Suggested questions (C37, Phase 10) ----------------------------------

  suggestions: {
    /**
     * GET /suggestions/starters — up to 3 session-start questions for the
     * empty-conversation "Try asking:" block. Session-less, no params. ALWAYS
     * 200 in the standard envelope: an empty workspace, an LLM failure, or the
     * offline stub all yield `{questions: []}` (never a 5xx) — callers hide the
     * block on an empty list (spec/api.md).
     */
    starters: () => getJson<StarterSuggestionsResponse>('/suggestions/starters'),
  },
}
