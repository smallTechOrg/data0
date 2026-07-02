'use client'

import { useCallback, useId, useState } from 'react'
import {
  ApiError,
  api,
  type ConnectionCheckResponse,
  type ConnectionImportResponse,
  type ConnectorTableInfo,
} from '@/lib/api'

/**
 * Connect a database (BETA) — C36, Phase 9.
 *
 * Minimal single-card affordance, rendered from `DatabaseTab.tsx` inside the
 * shared `.left-column-stack` (below the merged Upload/Tables card), and
 * ONLY when `GET /connections/status` reports the BETA flag on — the parent
 * decides whether to mount this component at all.
 *
 * Flow (all local `useState`, no global state):
 *  1. Pick a type (only PostgreSQL ships — the dropdown has one option, not
 *     implying other engines work yet) and paste a connection URI.
 *  2. "Test Connection" → `POST /connections/check` — nothing is persisted;
 *     on success the discovered tables render as a checklist.
 *  3. Select one or more tables → "Import" → `POST /connections/import` —
 *     each table is attempted independently, so a per-table result list is
 *     always shown (ok/error), never a single all-or-nothing outcome.
 *  4. On any successful import, `onImported()` is called so the parent can
 *     refresh the existing Tables list — mirrors how `UploadCard` calls
 *     `onUploaded()` after a successful upload.
 *
 * Credential hygiene: the raw URI lives only in this component's own state
 * for as long as it takes to submit a check/import request. It is never
 * logged (no `console.log` of `uri` anywhere in this file), never echoed
 * back (the API never returns it — see `spec/capabilities/external-db-connectors.md`),
 * and is cleared from state immediately once an import request has been
 * submitted. The input itself is a password field so the value isn't shown
 * on-screen while typing.
 */
export function ConnectDatabaseCard({ onImported }: { onImported: () => void }) {
  const headingId = useId()
  const typeId = useId()
  const uriId = useId()

  const [uri, setUri] = useState('')

  const [testing, setTesting] = useState(false)
  const [checkError, setCheckError] = useState<string | null>(null)
  const [checkResult, setCheckResult] = useState<ConnectionCheckResponse | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<ConnectionImportResponse | null>(null)

  const resetForNewAttempt = useCallback(() => {
    setCheckResult(null)
    setCheckError(null)
    setSelected(new Set())
    setImportResult(null)
    setImportError(null)
  }, [])

  const handleTest = useCallback(async () => {
    const trimmed = uri.trim()
    if (!trimmed) return
    setTesting(true)
    resetForNewAttempt()
    try {
      const result = await api.connections.check({ type: CONNECTOR_TYPE, uri: trimmed })
      setCheckResult(result)
    } catch (err) {
      setCheckError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to test the connection.',
      )
    } finally {
      setTesting(false)
    }
  }, [uri, resetForNewAttempt])

  const toggleTable = useCallback((tableName: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(tableName)) next.delete(tableName)
      else next.add(tableName)
      return next
    })
  }, [])

  const handleImport = useCallback(async () => {
    const trimmed = uri.trim()
    if (selected.size === 0 || !trimmed) return
    setImporting(true)
    setImportError(null)
    setImportResult(null)
    try {
      const result = await api.connections.import({
        type: CONNECTOR_TYPE,
        uri: trimmed,
        tables: Array.from(selected).map(table_name => ({ table_name })),
      })
      setImportResult(result)
      if (result.results.some(r => r.status === 'ok')) onImported()
    } catch (err) {
      setImportError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to import the selected tables.',
      )
    } finally {
      // Credential minimization: the raw URI is only needed to submit the
      // check/import requests — drop it from client state once the import
      // attempt (success or failure) has been made.
      setUri('')
      setImporting(false)
    }
  }, [selected, uri, onImported])

  const handleConnectAnother = useCallback(() => {
    resetForNewAttempt()
  }, [resetForNewAttempt])

  return (
    <section aria-labelledby={headingId} className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <h2 id={headingId} className="text-sm font-semibold text-gray-800">
          Connect a database
        </h2>
        <span className="rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
          BETA
        </span>
      </div>

      {!importResult ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor={typeId} className="text-[11px] font-medium text-gray-500">
              Type
            </label>
            {/* Only PostgreSQL ships in this phase — a single-option select
                rather than a text badge, so the seam reads as extensible
                (more engines land here later) without implying any of them
                work today. */}
            <select
              id={typeId}
              value={CONNECTOR_TYPE}
              disabled
              className="rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs text-gray-700"
            >
              <option value={CONNECTOR_TYPE}>PostgreSQL</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor={uriId} className="text-[11px] font-medium text-gray-500">
              Connection URI
            </label>
            <input
              id={uriId}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={uri}
              onChange={e => setUri(e.target.value)}
              placeholder="postgresql://user:password@host:5432/db"
              className="rounded-md border border-gray-200 px-2 py-1.5 text-xs text-gray-800 placeholder:text-gray-400 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <p className="text-[11px] text-gray-400">
              Read-only credentials recommended. Never shown or logged after submission.
            </p>
          </div>

          <div>
            <button
              type="button"
              onClick={() => void handleTest()}
              disabled={testing || !uri.trim()}
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {testing && <Spinner />}
              {testing ? 'Testing…' : 'Test Connection'}
            </button>
          </div>

          {checkError && (
            <p
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
            >
              {checkError}
            </p>
          )}

          {checkResult && (
            <div className="flex flex-col gap-2">
              {checkResult.tables.length === 0 ? (
                <p className="rounded-md border border-dashed border-gray-200 px-3 py-4 text-center text-xs text-gray-400">
                  No tables found in this database.
                </p>
              ) : (
                <>
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                    {checkResult.tables.length} table
                    {checkResult.tables.length === 1 ? '' : 's'} found — select which to import
                  </p>
                  <ul
                    role="list"
                    aria-label="Discovered tables"
                    className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-gray-200 p-2"
                  >
                    {checkResult.tables.map(t => (
                      <li key={t.table_name}>
                        <label className="flex items-center gap-2 rounded px-1.5 py-1 text-xs text-gray-700 hover:bg-gray-50">
                          <input
                            type="checkbox"
                            checked={selected.has(t.table_name)}
                            onChange={() => toggleTable(t.table_name)}
                          />
                          <span className="font-medium">{t.table_name}</span>
                          <span className="text-gray-400">{columnCountLabel(t)}</span>
                        </label>
                      </li>
                    ))}
                  </ul>

                  {importError && (
                    <p
                      role="alert"
                      className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
                    >
                      {importError}
                    </p>
                  )}

                  <div>
                    <button
                      type="button"
                      onClick={() => void handleImport()}
                      disabled={importing || selected.size === 0}
                      className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {importing && <Spinner />}
                      {importing
                        ? 'Importing…'
                        : `Import${selected.size > 0 ? ` (${selected.size})` : ''}`}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-gray-600">
            {importResult.results.filter(r => r.status === 'ok').length} of{' '}
            {importResult.results.length} table
            {importResult.results.length === 1 ? '' : 's'} imported.
          </p>
          <ul role="list" aria-label="Import results" className="space-y-1">
            {importResult.results.map(r => (
              <li
                key={r.table_name}
                role={r.status === 'error' ? 'alert' : undefined}
                className={`rounded-md border px-2.5 py-1.5 text-xs ${
                  r.status === 'ok'
                    ? 'border-green-200 bg-green-50 text-green-700'
                    : 'border-red-200 bg-red-50 text-red-700'
                }`}
              >
                {r.status === 'ok' ? (
                  <span>&#10003; {r.table_name} imported</span>
                ) : (
                  <span>
                    &#10007; {r.table_name}: {r.message ?? 'Import failed'}
                  </span>
                )}
              </li>
            ))}
          </ul>
          <div>
            <button
              type="button"
              onClick={handleConnectAnother}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              Connect another database
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

/** Only PostgreSQL ships in this phase (spec/capabilities/external-db-connectors.md). */
const CONNECTOR_TYPE = 'postgresql'

/** "N columns" label for a discovered table row, or '' if the count is unknown. */
function columnCountLabel(t: ConnectorTableInfo): string {
  const count = t.column_names?.length ?? t.schema?.length
  if (typeof count !== 'number') return ''
  return `${count} column${count === 1 ? '' : 's'}`
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  )
}
