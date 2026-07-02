'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  ApiError,
  type DatasetDetail,
  type PreviewResponse,
} from '@/lib/api'
import { _erKeysFor, type ErDataset, type ErKeys } from '@/components/database/ERDiagramPanel'
import { CleanModal } from '@/components/database/CleanModal'

/**
 * Table Description panel — REAL (Phase 4).
 *
 * Shows everything about the selected dataset (spec/ui.md "Table Description
 * panel"):
 *  - filename + origin/stale badges + "rows × cols · FORMAT";
 *  - a derived block (parent chips + collapsible derivation code) when derived;
 *  - a Keys block whose PK/FK come from `_erKeysFor` — the SAME inference the ER
 *    diagram uses (imported, never re-implemented), so badges and edges agree;
 *  - a columns table (Name | Type with PK/FK badges) from `columns_schema`;
 *  - a Context-notes textarea that AUTO-SAVES (debounced) via PATCH
 *    /datasets/{id}/context, plus a "Generate notes" button that POSTs /describe
 *    then polls GET /datasets/{id} on `auto_notes_status` until done/failed;
 *  - a ~10-row data preview via GET /datasets/{id}/preview;
 *  - actions: Clean (modal), Re-derive (derived+stale only), Delete (confirm).
 */
export function TableDescriptionPanel({
  datasetId,
  allDatasets,
  onChanged,
  onDeleted,
  onCollapse,
}: {
  datasetId: string | null
  allDatasets: ErDataset[]
  /** Called after a mutation that changes counts/columns (clean / re-derive / notes). */
  onChanged: () => void
  /** Called after a successful delete with the deleted id. */
  onDeleted: (id: string) => void
  /** Collapse this panel (hide it, giving the diagram full width). */
  onCollapse?: () => void
}) {
  const [detail, setDetail] = useState<DatasetDetail | null>(null)
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [showCode, setShowCode] = useState(false)
  const [cleanOpen, setCleanOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState<null | 'rederive' | 'delete' | 'describe' | 'resync'>(null)

  // Context-notes editing (debounced auto-save).
  const [notes, setNotes] = useState('')
  const [savingNotes, setSavingNotes] = useState(false)
  const [savedNotes, setSavedNotes] = useState(false)
  const [notesStatus, setNotesStatus] = useState<string | null>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // --- load detail + preview when the selection changes --------------------
  const loadDetail = useCallback(
    async (id: string) => {
      setLoading(true)
      setError(null)
      try {
        const [d, p] = await Promise.all([
          api.getDataset(id),
          api.preview(id, 10).catch(() => null),
        ])
        setDetail(d)
        setPreview(p)
        setNotes(d.context ?? '')
        setNotesStatus(d.auto_notes_status ?? null)
        setShowCode(false)
        setConfirmDelete(false)
        setSavedNotes(false)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load dataset details.')
        setDetail(null)
        setPreview(null)
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    // Clear any in-flight timers when the selection changes / unmounts.
    if (saveTimer.current) clearTimeout(saveTimer.current)
    if (pollTimer.current) clearTimeout(pollTimer.current)
    if (!datasetId) {
      setDetail(null)
      setPreview(null)
      setNotes('')
      setNotesStatus(null)
      return
    }
    void loadDetail(datasetId)
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      if (pollTimer.current) clearTimeout(pollTimer.current)
    }
  }, [datasetId, loadDetail])

  // --- keys (PK/FK) from the single-source-of-truth inference --------------
  const keys: ErKeys = useMemo(
    () => (datasetId ? _erKeysFor(datasetId, allDatasets) : { pk: [], fk: [] }),
    [datasetId, allDatasets],
  )
  const pkSet = useMemo(() => new Set(keys.pk), [keys.pk])
  const fkMap = useMemo(
    () => new Map(keys.fk.map(f => [f.column, f.references] as const)),
    [keys.fk],
  )

  // --- context notes: debounced auto-save ----------------------------------
  const onNotesChange = useCallback(
    (value: string) => {
      setNotes(value)
      setSavedNotes(false)
      if (!datasetId) return
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(() => {
        setSavingNotes(true)
        api
          .patchContext(datasetId, value)
          .then(() => {
            setSavedNotes(true)
            onChanged()
          })
          .catch((err: unknown) => {
            setError(err instanceof Error ? err.message : 'Failed to save notes.')
          })
          .finally(() => setSavingNotes(false))
      }, 800)
    },
    [datasetId, onChanged],
  )

  // --- Generate notes (C30): trigger then poll auto_notes_status -----------
  const pollNotes = useCallback(
    (id: string, attempt = 0) => {
      pollTimer.current = setTimeout(async () => {
        try {
          const d = await api.getDataset(id)
          setNotesStatus(d.auto_notes_status ?? null)
          if (d.auto_notes_status === 'done' || d.auto_notes_status === 'failed') {
            if (d.auto_notes_status === 'done') {
              setNotes(d.context ?? '')
              setDetail(prev => (prev ? { ...prev, context: d.context } : d))
              onChanged()
            }
            setBusy(null)
            return
          }
        } catch {
          // transient — keep polling within the budget
        }
        if (attempt < 40) pollNotes(id, attempt + 1)
        else setBusy(null) // give up after ~80s; status stays "pending"
      }, 2000)
    },
    [onChanged],
  )

  const generateNotes = useCallback(async () => {
    if (!datasetId) return
    setBusy('describe')
    setError(null)
    setNotesStatus('pending')
    try {
      await api.describeDataset(datasetId)
      pollNotes(datasetId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start notes generation.')
      setNotesStatus(detail?.auto_notes_status ?? null)
      setBusy(null)
    }
  }, [datasetId, pollNotes, detail])

  // --- Re-derive (C25; derived + stale only) -------------------------------
  const doReDerive = useCallback(async () => {
    if (!datasetId) return
    setBusy('rederive')
    setError(null)
    try {
      await api.reDerive(datasetId)
      await loadDetail(datasetId)
      onChanged()
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to re-derive the dataset.',
      )
    } finally {
      setBusy(null)
    }
  }, [datasetId, loadDetail, onChanged])

  // --- Re-sync (C36; connected datasets only) -------------------------------
  const doResync = useCallback(async () => {
    if (!datasetId) return
    setBusy('resync')
    setError(null)
    try {
      await api.connections.resync(datasetId)
      await loadDetail(datasetId)
      onChanged()
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to re-sync the dataset.',
      )
    } finally {
      setBusy(null)
    }
  }, [datasetId, loadDetail, onChanged])

  // --- Delete --------------------------------------------------------------
  const doDelete = useCallback(async () => {
    if (!datasetId) return
    setBusy('delete')
    setError(null)
    try {
      await api.deleteDataset(datasetId)
      setConfirmDelete(false)
      onDeleted(datasetId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete the dataset.')
    } finally {
      setBusy(null)
    }
  }, [datasetId, onDeleted])

  // --- render --------------------------------------------------------------
  return (
    <TableDescriptionPanelView
      datasetId={datasetId}
      detail={detail}
      preview={preview}
      loading={loading}
      error={error}
      keys={keys}
      pkSet={pkSet}
      fkMap={fkMap}
      allDatasets={allDatasets}
      notes={notes}
      savingNotes={savingNotes}
      savedNotes={savedNotes}
      notesStatus={notesStatus}
      showCode={showCode}
      cleanOpen={cleanOpen}
      confirmDelete={confirmDelete}
      busy={busy}
      onCollapse={onCollapse}
      onToggleCode={() => setShowCode(v => !v)}
      onRetry={() => datasetId && void loadDetail(datasetId)}
      onNotesChange={onNotesChange}
      onGenerateNotes={() => void generateNotes()}
      onReDerive={() => void doReDerive()}
      onResync={() => void doResync()}
      onOpenClean={() => setCleanOpen(true)}
      onCloseClean={() => setCleanOpen(false)}
      onCleanApplied={id => {
        setCleanOpen(false)
        void loadDetail(id)
        onChanged()
      }}
      onRequestDelete={() => setConfirmDelete(true)}
      onCancelDelete={() => setConfirmDelete(false)}
      onConfirmDelete={() => void doDelete()}
    />
  )
}

/**
 * Presentational view for the Table Description panel — PURE.
 *
 * Renders the entire panel (badges, lineage, keys, columns, context notes,
 * preview, actions, and the embedded {@link CleanModal}) from props alone. It
 * holds NO data-loading or mutation logic: every displayed value and every
 * action arrives via props from {@link TableDescriptionPanel}.
 */
export interface TableDescriptionPanelViewProps {
  /** Currently-selected dataset id (null ⇒ empty state). */
  datasetId: string | null
  /** Loaded detail for the selection, or null while empty/loading/errored. */
  detail: DatasetDetail | null
  /** ~10-row data preview, or null when unavailable. */
  preview: PreviewResponse | null
  /** True while the initial detail load is in flight. */
  loading: boolean
  /** Fatal (no detail) or inline (with detail) error message, or null. */
  error: string | null
  /** Inferred PK/FK keys (single source of truth, shared with the ER diagram). */
  keys: ErKeys
  /** Set of column names that are primary keys (for the columns table badges). */
  pkSet: Set<string>
  /** Map of FK column name → referenced table (for the columns table badges). */
  fkMap: Map<string, string>
  /** All datasets, used to resolve parent ids → filenames in the lineage block. */
  allDatasets: ErDataset[]
  /** Current value of the editable context-notes textarea. */
  notes: string
  /** True while a debounced notes auto-save is in flight. */
  savingNotes: boolean
  /** True briefly after a successful notes auto-save. */
  savedNotes: boolean
  /** Auto-notes generation status ('pending' | 'done' | 'failed' | null). */
  notesStatus: string | null
  /** Whether the derivation-code block is expanded. */
  showCode: boolean
  /** Whether the clean modal is open. */
  cleanOpen: boolean
  /** Whether the inline delete confirmation is showing. */
  confirmDelete: boolean
  /** Which long-running mutation is active, or null. */
  busy: null | 'rederive' | 'delete' | 'describe' | 'resync'
  /** Collapse this panel (hide it), when provided. */
  onCollapse?: () => void
  /** Toggle the derivation-code block. */
  onToggleCode: () => void
  /** Retry loading after a fatal load error. */
  onRetry: () => void
  /** Edit the context-notes value (drives debounced auto-save in the container). */
  onNotesChange: (value: string) => void
  /** Trigger LLM notes generation. */
  onGenerateNotes: () => void
  /** Re-derive a derived+stale dataset. */
  onReDerive: () => void
  /** C36 — manually re-pull a connected dataset's source table. */
  onResync: () => void
  /** Open the clean modal. */
  onOpenClean: () => void
  /** Close the clean modal. */
  onCloseClean: () => void
  /** A clean was applied to the given dataset id. */
  onCleanApplied: (id: string) => void
  /** Show the delete confirmation. */
  onRequestDelete: () => void
  /** Dismiss the delete confirmation. */
  onCancelDelete: () => void
  /** Confirm and perform the delete. */
  onConfirmDelete: () => void
}

export function TableDescriptionPanelView({
  datasetId,
  detail,
  preview,
  loading,
  error,
  keys,
  pkSet,
  fkMap,
  allDatasets,
  notes,
  savingNotes,
  savedNotes,
  notesStatus,
  showCode,
  cleanOpen,
  confirmDelete,
  busy,
  onCollapse,
  onToggleCode,
  onRetry,
  onNotesChange,
  onGenerateNotes,
  onReDerive,
  onResync,
  onOpenClean,
  onCloseClean,
  onCleanApplied,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: TableDescriptionPanelViewProps) {
  const derived = detail?.origin === 'derived'
  const stale = detail?.stale === true
  const parentIds = detail?.derived_from_dataset_ids ?? []
  const nameById = useMemo(
    () => new Map(allDatasets.map(d => [d.id, d.filename] as const)),
    [allDatasets],
  )

  return (
    <section
      aria-labelledby="description-heading"
      className="flex flex-col rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="description-heading" className="text-sm font-semibold text-gray-800">
          Table description
        </h2>
        <div className="flex items-center gap-1.5">
          {derived && (
            <span className="inline-flex items-center gap-1.5">
              <span className="rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700">
                derived
              </span>
              {stale && (
                <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                  stale
                </span>
              )}
            </span>
          )}
          {onCollapse && (
            <button
              type="button"
              onClick={onCollapse}
              aria-label="Collapse description panel"
              title="Collapse panel — give the diagram the full width"
              className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-50"
            >
              Hide ›
            </button>
          )}
        </div>
      </div>

      {!datasetId ? (
        <div className="rounded-md border border-dashed border-gray-200 px-3 py-10 text-center text-xs text-gray-400">
          Select a dataset in the diagram to see its details.
        </div>
      ) : loading && !detail ? (
        <div className="rounded-md border border-dashed border-gray-200 px-3 py-10 text-center text-xs text-gray-400">
          Loading dataset details…
        </div>
      ) : error && !detail ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-6 text-center text-xs text-red-700"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={onRetry}
            className="rounded border border-red-300 bg-white px-2 py-0.5 font-medium text-red-700 hover:bg-red-100"
          >
            Retry
          </button>
        </div>
      ) : detail ? (
        <div className="flex flex-col gap-4">
          {/* Inline (non-fatal) error banner */}
          {error && (
            <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </p>
          )}

          {/* Filename + size summary */}
          <div>
            <p className="truncate text-sm font-semibold text-gray-900" title={detail.filename}>
              {detail.filename}
            </p>
            <p className="mt-0.5 text-xs text-gray-500 tabular-nums">
              {detail.row_count.toLocaleString()} rows × {detail.col_count} cols ·{' '}
              {detail.format?.toUpperCase()}
            </p>
            {/* C36 (Phase 9, BETA) — provenance readout for a connected dataset.
                Credential-free: only `source_uri_display` (never the raw URI)
                and `source_table_name` are shown. */}
            {detail.source_type && (
              <p className="mt-1 text-[11px] text-gray-500">
                from {connectorDisplayName(detail.source_type)}:{' '}
                {detail.source_uri_display && (
                  <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[11px] text-gray-600">
                    {detail.source_uri_display}
                  </code>
                )}
                {detail.source_table_name && (
                  <>
                    {' · '}
                    <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[11px] text-gray-600">
                      {detail.source_table_name}
                    </code>
                  </>
                )}
              </p>
            )}
          </div>

          {/* Derived lineage block */}
          {derived && (
            <div className="rounded-md border border-green-100 bg-green-50/60 p-3">
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-green-700">
                Derived from
              </p>
              {detail.derivation_description && (
                <p className="mb-2 text-xs text-gray-600">{detail.derivation_description}</p>
              )}
              <div className="flex flex-wrap gap-1.5">
                {parentIds.length === 0 ? (
                  <span className="text-xs text-gray-400">No parent datasets recorded.</span>
                ) : (
                  parentIds.map(pid => (
                    <span
                      key={pid}
                      className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-700"
                    >
                      {nameById.get(pid) ?? pid}
                    </span>
                  ))
                )}
              </div>
              {detail.derivation_code && (
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={onToggleCode}
                    aria-expanded={showCode ? 'true' : 'false'}
                    className="text-[11px] font-medium text-green-700 hover:text-green-900"
                  >
                    {showCode ? 'Hide' : 'Show'} derivation code
                  </button>
                  {showCode && (
                    <pre className="mt-1.5 overflow-x-auto rounded-md bg-gray-900 px-3 py-2 font-mono text-[11px] leading-relaxed text-gray-100">
                      <code>{detail.derivation_code}</code>
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Keys block (PK/FK from _erFkLinks) */}
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              Keys
            </p>
            {keys.pk.length === 0 && keys.fk.length === 0 ? (
              <p className="text-xs text-gray-400">No inferred keys.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {keys.pk.map(col => (
                  <span
                    key={`pk-${col}`}
                    className="inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800"
                  >
                    <span className="font-bold">PK</span>
                    {col}
                  </span>
                ))}
                {keys.fk.map(f => (
                  <span
                    key={`fk-${f.column}`}
                    className="inline-flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-800"
                    title={`References ${f.references}`}
                  >
                    <span className="font-bold">FK</span>
                    {f.column} → {f.references}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Columns table */}
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              Columns
            </p>
            <div className="overflow-hidden rounded-md border border-gray-200">
              <table className="w-full text-left text-xs">
                <thead className="bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-2.5 py-1.5 font-medium">Name</th>
                    <th className="px-2.5 py-1.5 font-medium">Type</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.columns_schema.map((c, i) => {
                    const isPk = pkSet.has(c.name)
                    const fkRef = fkMap.get(c.name)
                    return (
                      <tr key={c.name} className={i % 2 === 1 ? 'bg-gray-50/60' : undefined}>
                        <td className="px-2.5 py-1.5 font-medium text-gray-800">
                          <span className="inline-flex items-center gap-1.5">
                            {c.name}
                            {isPk && (
                              <span className="rounded border border-amber-200 bg-amber-50 px-1 text-[10px] font-bold text-amber-700">
                                PK
                              </span>
                            )}
                            {fkRef && (
                              <span
                                className="rounded border border-blue-200 bg-blue-50 px-1 text-[10px] font-bold text-blue-700"
                                title={`References ${fkRef}`}
                              >
                                FK
                              </span>
                            )}
                          </span>
                        </td>
                        <td className="px-2.5 py-1.5 text-gray-500">{c.dtype}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Context notes (auto-save) + Generate notes (C30) */}
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label
                htmlFor="context-notes"
                className="text-[11px] font-semibold uppercase tracking-wide text-gray-500"
              >
                Context notes
              </label>
              <span className="flex items-center gap-2 text-[11px] text-gray-400">
                {savingNotes ? (
                  <span>Saving…</span>
                ) : savedNotes ? (
                  <span className="text-green-600">Saved</span>
                ) : null}
                <button
                  type="button"
                  onClick={onGenerateNotes}
                  disabled={busy === 'describe' || notesStatus === 'pending'}
                  className="generate-notes-btn inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {(busy === 'describe' || notesStatus === 'pending') && <Spinner />}
                  {notesStatus === 'pending' ? 'Generating…' : 'Generate notes'}
                </button>
              </span>
            </div>
            <textarea
              id="context-notes"
              rows={3}
              value={notes}
              onChange={e => onNotesChange(e.target.value)}
              placeholder="Add context about this dataset (units, caveats, what columns mean)…"
              className="w-full resize-y rounded-md border border-gray-200 p-2.5 text-xs text-gray-800 placeholder:text-gray-400 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            {notesStatus === 'failed' && (
              <p className="mt-1 text-[11px] text-amber-700">
                Notes generation failed. You can edit the notes manually or try again.
              </p>
            )}
          </div>

          {/* Data preview (~10 rows) */}
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              Preview
            </p>
            {preview && preview.columns.length > 0 ? (
              <div className="overflow-x-auto rounded-md border border-gray-200">
                <table className="w-full text-left text-[11px]">
                  <thead className="bg-gray-50 uppercase tracking-wide text-gray-500">
                    <tr>
                      {preview.columns.map(col => (
                        <th key={col} className="whitespace-nowrap px-2.5 py-1.5 font-medium">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row, ri) => (
                      <tr key={ri} className={ri % 2 === 1 ? 'bg-gray-50/60' : undefined}>
                        {preview.columns.map((col, ci) => (
                          <td
                            key={col}
                            className="whitespace-nowrap px-2.5 py-1.5 tabular-nums text-gray-700"
                          >
                            {formatCell(cellValue(row, col, ci))}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="rounded-md border border-dashed border-gray-200 px-3 py-4 text-center text-xs text-gray-400">
                No preview rows available.
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 pt-3">
            <button
              type="button"
              onClick={onOpenClean}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              Clean
            </button>

            {derived && stale && (
              <button
                type="button"
                onClick={onReDerive}
                disabled={busy === 'rederive'}
                className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy === 'rederive' && <Spinner />}
                {busy === 'rederive' ? 'Re-deriving…' : 'Re-derive'}
              </button>
            )}

            {/* C36 (Phase 9, BETA) — manual re-pull for a connected dataset;
                there is no automatic staleness flag for these, so this is
                always available (not gated on a "stale" condition). */}
            {detail.source_type && (
              <button
                type="button"
                onClick={onResync}
                disabled={busy === 'resync'}
                className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy === 'resync' && <Spinner />}
                {busy === 'resync' ? 'Re-syncing…' : 'Re-sync'}
              </button>
            )}

            <span className="ml-auto">
              {confirmDelete ? (
                <span className="inline-flex items-center gap-2">
                  <span className="text-xs text-gray-600">Delete this dataset?</span>
                  <button
                    type="button"
                    onClick={onConfirmDelete}
                    disabled={busy === 'delete'}
                    className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busy === 'delete' && <Spinner />}
                    {busy === 'delete' ? 'Deleting…' : 'Yes'}
                  </button>
                  <button
                    type="button"
                    onClick={onCancelDelete}
                    disabled={busy === 'delete'}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60"
                  >
                    No
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={onRequestDelete}
                  className="rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100"
                >
                  Delete
                </button>
              )}
            </span>
          </div>
        </div>
      ) : null}

      {/* NL cleaning modal (C24) */}
      <CleanModal
        datasetId={cleanOpen ? datasetId : null}
        filename={detail?.filename ?? null}
        open={cleanOpen}
        onClose={onCloseClean}
        onApplied={onCleanApplied}
      />
    </section>
  )
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  )
}

/** Human-readable label for a C36 connector `source_type` (e.g. "postgresql" → "PostgreSQL"). */
function connectorDisplayName(sourceType: string): string {
  if (sourceType.toLowerCase() === 'postgresql' || sourceType.toLowerCase() === 'postgres') {
    return 'PostgreSQL'
  }
  return sourceType.charAt(0).toUpperCase() + sourceType.slice(1)
}

/** Read a preview cell — the API returns row OBJECTS keyed by column name. */
function cellValue(row: unknown, col: string, index: number): unknown {
  if (Array.isArray(row)) return row[index]
  if (row && typeof row === 'object') return (row as Record<string, unknown>)[col]
  return undefined
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

