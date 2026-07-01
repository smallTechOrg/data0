'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  type ColumnSchema,
  type DatasetSummary,
} from '@/lib/api'
import { CleanModal } from '@/components/database/CleanModal'

/**
 * Datasets / "Tables" card — REAL, multi-select; derived-aware in Phase 4.
 *
 * Fetches GET /datasets on mount and whenever `datasetsVersion` changes (the
 * parent bumps it after each upload and each completed ask, surfacing new /
 * derived datasets). Each row shows filename + rows×cols + format, with the
 * dataset's **origin/state conveyed by the whole-pill tint** (uploaded = neutral,
 * derived = green, stale = amber — no text badge), a checkbox to select the
 * dataset for bulk actions, a **columns** icon toggle that lazily fetches
 * GET /datasets/{id} for the column schema, a **Clean** (broom) icon action
 * (uploaded rows → the C24 clean modal) and a **Re-derive** action (stale
 * derived rows → POST /datasets/{id}/re-derive). Deletion is a
 * bulk action in the selection bar: check rows, then **Delete selected** with an
 * inline confirm → DELETE /datasets/{id} for each checked dataset. The selection
 * does NOT scope analysis — dataset selection for a question is agent-driven
 * server-side (the agent picks from a catalog of all datasets).
 *
 * The filter tabs (All|Uploaded|Derived|Selected) are REAL client-side
 * filters by `origin` / current selection.
 */

const FILTERS = ['All', 'Uploaded', 'Derived', 'Selected'] as const
type Filter = (typeof FILTERS)[number]

export interface ColsState {
  loading: boolean
  error: string | null
  columns: ColumnSchema[] | null
}

/**
 * Row "tone" — the dataset's origin/state, conveyed by the whole pill's colour
 * instead of a text badge: uploaded = neutral (no tint), derived = green, stale = amber.
 * `stale` is the most specific state and wins over plain `derived`.
 */
type RowTone = 'uploaded' | 'derived' | 'stale'

function rowTone(ds: DatasetSummary): RowTone {
  if (ds.origin === 'derived') return ds.stale === true ? 'stale' : 'derived'
  return 'uploaded'
}

/** Whole-pill tint per tone — resting vs selected (selected = deeper + ring). */
const TONE_PILL: Record<RowTone, { rest: string; selected: string }> = {
  uploaded: {
    rest: 'border-gray-200 bg-white hover:bg-gray-50',
    selected: 'border-blue-300 bg-blue-50 ring-1 ring-inset ring-blue-300',
  },
  derived: {
    rest: 'border-green-200 bg-green-50 hover:bg-green-100/60',
    selected: 'border-green-400 bg-green-100 ring-1 ring-inset ring-green-400',
  },
  stale: {
    rest: 'border-amber-200 bg-amber-50 hover:bg-amber-100/60',
    selected: 'border-amber-400 bg-amber-100 ring-1 ring-inset ring-amber-400',
  },
}

/** Checkbox accent per tone, so a checked row echoes its pill colour. */
const TONE_ACCENT: Record<RowTone, string> = {
  uploaded: 'accent-blue-600',
  derived: 'accent-green-600',
  stale: 'accent-amber-600',
}

/** Screen-reader origin/state label (replaces the removed visible badge). */
const TONE_LABEL: Record<RowTone, string> = {
  uploaded: 'Uploaded dataset',
  derived: 'Derived dataset',
  stale: 'Stale derived dataset — a parent changed after it was derived',
}

/** Framed 3-column grid glyph for the "cols" toggle. */
function ColumnsIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="16" rx="1.5" />
      <line x1="9" y1="4" x2="9" y2="20" />
      <line x1="15" y1="4" x2="15" y2="20" />
    </svg>
  )
}

/** Broom glyph for the "Clean" action (handle + bristle head). */
function BroomIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 4 11 13" />
      <path d="M7 17 11 13 15 17 11 21 Z" />
      <path d="M9 19 8 22" />
      <path d="M11 19.5 11 22.5" />
      <path d="M13 19 14 22" />
    </svg>
  )
}

/**
 * Presentational view for {@link TablesCard}.
 *
 * PURE: renders the datasets list, selection bar, filter tabs and per-row
 * actions entirely from props — no `useEffect`, no `api.*`, no data loading.
 * The filter-tab selection is purely-local UI state and lives here. All
 * displayed values arrive as props and every action is an `on*` callback the
 * container wires to its load/refresh/`api.*` logic.
 */
export interface TablesCardViewProps {
  /** All datasets to render (already loaded by the container). */
  datasets: DatasetSummary[]
  /** True while the initial load is in flight (first paint only). */
  loading: boolean
  /** Load/action error to surface in the shared banner, or null. */
  error: string | null
  /** Ids of datasets selected for bulk actions (delete). Does NOT scope analysis. */
  selectedDatasetIds: string[]
  /** Per-row "cols" disclosure state, keyed by dataset id. */
  colsById: Record<string, ColsState>
  /** True while a bulk delete is in flight. */
  deletingBulk: boolean
  /** Id of the derived dataset currently re-deriving, or null. */
  rederivingId: string | null
  /** Re-run the dataset load. */
  onRefresh: () => void
  /** Select/deselect a single dataset. */
  onToggleSelect: (id: string) => void
  /** Select every dataset id. */
  onSelectAll: (ids: string[]) => void
  /** Clear the selection. */
  onClearSelection: () => void
  /** Delete every currently-selected dataset. */
  onDeleteSelected: () => void
  /** Toggle (lazy-load / collapse) the column schema for a dataset. */
  onToggleCols: (id: string) => void
  /** Open the clean modal for an uploaded dataset. */
  onClean: (ds: DatasetSummary) => void
  /** Re-derive a stale derived dataset. */
  onReDerive: (id: string) => void
}

export function TablesCardView({
  datasets,
  loading,
  error,
  selectedDatasetIds,
  colsById,
  deletingBulk,
  rederivingId,
  onRefresh,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  onDeleteSelected,
  onToggleCols,
  onClean,
  onReDerive,
}: TablesCardViewProps) {
  const [filter, setFilter] = useState<Filter>('All')
  // Bulk-delete inline-confirm state (pure UI — lives with the view).
  const [confirmBulk, setConfirmBulk] = useState(false)

  // Client-side filter by origin / current selection (the filter tabs).
  const visibleDatasets = useMemo(() => {
    switch (filter) {
      case 'Uploaded':
        return datasets.filter(d => d.origin !== 'derived')
      case 'Derived':
        return datasets.filter(d => d.origin === 'derived')
      case 'Selected':
        // Show only the rows the user has checked (for bulk actions). Empty
        // selection → nothing to narrow to, so show all.
        return selectedDatasetIds.length > 0
          ? datasets.filter(d => selectedDatasetIds.includes(d.id))
          : datasets
      default:
        return datasets
    }
  }, [datasets, filter, selectedDatasetIds])

  // Ids of the rows currently shown under the active filter. "Select all" must
  // pin exactly these (not every dataset), and the count of how many of them are
  // already selected drives the disabled/visible state of the affordance.
  const visibleIds = useMemo(() => visibleDatasets.map(d => d.id), [visibleDatasets])
  const visibleSelectedCount = useMemo(
    () => visibleIds.filter(id => selectedDatasetIds.includes(id)).length,
    [visibleIds, selectedDatasetIds],
  )

  const uploadedCount = datasets.filter(d => d.origin !== 'derived').length
  const derivedCount = datasets.filter(d => d.origin === 'derived').length

  return (
    <section
      aria-labelledby="tables-heading"
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 id="tables-heading" className="text-lg font-bold text-gray-900">
          Tables
        </h2>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
          aria-label="Refresh datasets"
        >
          Refresh
        </button>
      </div>

      {/* Selection bar for BULK ACTIONS (delete) — not analysis scoping.
          Action buttons are left-anchored (Select all is always present —
          disabled when everything is selected — so the cluster never shifts);
          the "N selected" count floats to the far right via ml-auto. */}
      {datasets.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-xs">
          <button
            type="button"
            onClick={() => onSelectAll(visibleIds)}
            disabled={visibleIds.length === 0 || visibleSelectedCount >= visibleIds.length}
            className="rounded border border-gray-300 bg-white px-2 py-0.5 font-medium text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:border-gray-200 disabled:bg-gray-50 disabled:text-gray-300"
          >
            Select all
          </button>
          {selectedDatasetIds.length > 0 && (
            <button
              type="button"
              onClick={onClearSelection}
              className="rounded border border-gray-300 bg-white px-2 py-0.5 font-medium text-gray-600 hover:bg-gray-50"
            >
              Clear
            </button>
          )}
          {selectedDatasetIds.length > 0 &&
            (confirmBulk ? (
              <span className="flex items-center gap-1">
                <span className="text-gray-600">
                  Delete {selectedDatasetIds.length} dataset
                  {selectedDatasetIds.length === 1 ? '' : 's'}?
                </span>
                <button
                  type="button"
                  onClick={onDeleteSelected}
                  disabled={deletingBulk}
                  className="rounded border border-red-300 bg-red-50 px-2 py-0.5 font-medium text-red-700 hover:bg-red-100 disabled:opacity-60"
                >
                  {deletingBulk ? 'Deleting…' : 'Yes, delete'}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmBulk(false)}
                  disabled={deletingBulk}
                  className="rounded border border-gray-300 bg-white px-2 py-0.5 font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmBulk(true)}
                className="rounded border border-red-300 bg-red-50 px-2 py-0.5 font-medium text-red-700 hover:bg-red-100"
              >
                Delete selected ({selectedDatasetIds.length})
              </button>
            ))}
          {selectedDatasetIds.length > 0 && (
            <span className="ml-auto font-medium text-gray-700">
              {`${selectedDatasetIds.length} dataset${
                selectedDatasetIds.length === 1 ? '' : 's'
              } selected`}
            </span>
          )}
        </div>
      )}

      {/* Filter tabs — REAL client-side filters by origin / selection. */}
      <div role="group" aria-label="Dataset filters" className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map(f => {
          const active = filter === f
          const count =
            f === 'Uploaded' ? uploadedCount : f === 'Derived' ? derivedCount : null
          return (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              aria-pressed={active}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${
                active
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-500 hover:bg-gray-50'
              }`}
            >
              {f}
              {count !== null && <span className="ml-1 text-gray-400">({count})</span>}
            </button>
          )
        })}
      </div>

      {/* States: loading / error / empty / list */}
      {loading && datasets.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-200 px-3 py-8 text-center text-xs text-gray-400">
          Loading datasets…
        </div>
      ) : error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-6 text-center text-xs text-red-700"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={onRefresh}
            className="rounded border border-red-300 bg-white px-2 py-0.5 font-medium text-red-700 hover:bg-red-100"
          >
            Retry
          </button>
        </div>
      ) : datasets.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-200 px-3 py-8 text-center text-xs text-gray-400">
          No datasets yet. Upload a CSV below to get started.
        </div>
      ) : visibleDatasets.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-200 px-3 py-8 text-center text-xs text-gray-400">
          No {filter.toLowerCase()} datasets.
        </div>
      ) : (
        <ul
          role="list"
          className="density-row-gap flex max-h-[24rem] flex-col overflow-y-auto pr-1"
        >
          {visibleDatasets.map(ds => {
            const cols = colsById[ds.id]
            const selected = selectedDatasetIds.includes(ds.id)
            const derived = ds.origin === 'derived'
            const stale = derived && ds.stale === true
            const tone = rowTone(ds)
            const pill = TONE_PILL[tone]
            return (
              <li
                key={ds.id}
                title={TONE_LABEL[tone]}
                className={`density-row-padding rounded-md border transition-colors ${
                  selected ? pill.selected : pill.rest
                }`}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <label className="flex min-w-0 flex-1 items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => onToggleSelect(ds.id)}
                      aria-label={`Select ${ds.filename}`}
                      className={`h-4 w-4 shrink-0 ${TONE_ACCENT[tone]}`}
                    />
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-gray-800">
                      {ds.filename}
                    </span>
                  </label>
                  {/* Origin/state is conveyed by the pill tint; this sr-only text
                      keeps that information available to screen readers (C-a11y). */}
                  <span className="sr-only">{TONE_LABEL[tone]}</span>

                  <span className="shrink-0 text-xs tabular-nums text-gray-500">
                    {ds.row_count} × {ds.col_count}
                  </span>
                  <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-500">
                    {ds.format}
                  </span>

                  <button
                    type="button"
                    onClick={() => onToggleCols(ds.id)}
                    aria-expanded={Boolean(cols)}
                    aria-label={`Toggle columns for ${ds.filename}`}
                    title="Columns"
                    className={`inline-flex shrink-0 items-center justify-center rounded p-1 text-gray-500 hover:bg-white/70 hover:text-gray-800 ${
                      cols ? 'bg-white/80 text-gray-800' : ''
                    }`}
                  >
                    <ColumnsIcon />
                  </button>

                  {/* Clean — uploaded datasets only (C24). */}
                  {!derived && (
                    <button
                      type="button"
                      onClick={() => onClean(ds)}
                      aria-label={`Clean ${ds.filename}`}
                      title="Clean"
                      className="inline-flex shrink-0 items-center justify-center rounded p-1 text-gray-500 hover:bg-white/70 hover:text-gray-800"
                    >
                      <BroomIcon />
                    </button>
                  )}

                  {/* Re-derive — stale derived datasets only (C25). */}
                  {stale && (
                    <button
                      type="button"
                      onClick={() => onReDerive(ds.id)}
                      disabled={rederivingId === ds.id}
                      aria-label={`Re-derive ${ds.filename}`}
                      title="Re-derive"
                      className="shrink-0 rounded border border-amber-400 bg-white/70 px-2 py-0.5 text-[11px] font-medium text-amber-800 hover:bg-white disabled:opacity-60"
                    >
                      {rederivingId === ds.id ? 'Re-deriving…' : 'Re-derive'}
                    </button>
                  )}
                </div>

                {/* Columns disclosure */}
                {cols && (
                  <div className="mt-2 border-t border-gray-100 pt-2">
                    {cols.loading ? (
                      <p className="text-xs text-gray-400">Loading columns…</p>
                    ) : cols.error ? (
                      <p role="alert" className="text-xs text-red-600">
                        {cols.error}
                      </p>
                    ) : cols.columns && cols.columns.length > 0 ? (
                      <ul className="flex flex-wrap gap-1.5">
                        {cols.columns.map(c => (
                          <li
                            key={c.name}
                            className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-700"
                          >
                            <span className="font-medium">{c.name}</span>
                            <span className="text-gray-400"> · {c.dtype}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-gray-400">No columns reported.</p>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

export function TablesCard({
  datasetsVersion,
  selectedDatasetIds,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  onDeleted,
}: {
  datasetsVersion: number
  selectedDatasetIds: string[]
  onToggleSelect: (id: string) => void
  onSelectAll: (ids: string[]) => void
  onClearSelection: () => void
  onDeleted: (id: string) => void
}) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Per-row "cols" expansion state, keyed by dataset id.
  const [colsById, setColsById] = useState<Record<string, ColsState>>({})
  // Bulk-delete in-flight state for the selection bar.
  const [deletingBulk, setDeletingBulk] = useState(false)
  // Which derived row is currently re-deriving.
  const [rederivingId, setRederivingId] = useState<string | null>(null)
  // The dataset the Clean modal is open for (uploaded rows only).
  const [cleanTarget, setCleanTarget] = useState<DatasetSummary | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await api.listDatasets()
      setDatasets(Array.isArray(list) ? list : [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load datasets.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, datasetsVersion])

  const toggleCols = useCallback(
    async (id: string) => {
      const current = colsById[id]
      if (current && !current.loading) {
        // Already loaded (or errored) → collapse by removing it.
        setColsById(prev => {
          const next = { ...prev }
          delete next[id]
          return next
        })
        return
      }
      setColsById(prev => ({ ...prev, [id]: { loading: true, error: null, columns: null } }))
      try {
        const detail = await api.getDataset(id)
        setColsById(prev => ({
          ...prev,
          [id]: { loading: false, error: null, columns: detail.columns_schema ?? [] },
        }))
      } catch (err) {
        setColsById(prev => ({
          ...prev,
          [id]: {
            loading: false,
            error: err instanceof Error ? err.message : 'Failed to load columns.',
            columns: null,
          },
        }))
      }
    },
    [colsById],
  )

  // Bulk-delete every checked dataset. Settles all deletions, drops the
  // ones that succeeded from the selection + local list, and surfaces the first
  // failure (if any) via the shared error banner.
  const deleteSelected = useCallback(async () => {
    const ids = [...selectedDatasetIds]
    if (ids.length === 0) return
    setDeletingBulk(true)
    setError(null)
    try {
      const results = await Promise.allSettled(ids.map(id => api.deleteDataset(id)))
      const succeeded: string[] = []
      let firstError: string | null = null
      results.forEach((result, i) => {
        const id = ids[i]
        if (result.status === 'fulfilled') {
          succeeded.push(id)
          onDeleted(id)
        } else if (!firstError) {
          firstError =
            result.reason instanceof Error
              ? result.reason.message
              : 'Failed to delete dataset.'
        }
      })
      // Optimistic local removal in case the parent refresh lags.
      if (succeeded.length > 0) {
        setDatasets(prev => prev.filter(d => !succeeded.includes(d.id)))
      }
      if (firstError) setError(firstError)
    } finally {
      setDeletingBulk(false)
    }
  }, [selectedDatasetIds, onDeleted])

  // Re-derive a stale derived dataset (C25), then refresh to clear the badge.
  const reDerive = useCallback(
    async (id: string) => {
      setRederivingId(id)
      setError(null)
      try {
        await api.reDerive(id)
        await load()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to re-derive dataset.')
      } finally {
        setRederivingId(null)
      }
    },
    [load],
  )

  return (
    <>
      <TablesCardView
        datasets={datasets}
        loading={loading}
        error={error}
        selectedDatasetIds={selectedDatasetIds}
        colsById={colsById}
        deletingBulk={deletingBulk}
        rederivingId={rederivingId}
        onRefresh={() => void load()}
        onToggleSelect={onToggleSelect}
        onSelectAll={onSelectAll}
        onClearSelection={onClearSelection}
        onDeleteSelected={() => void deleteSelected()}
        onToggleCols={id => void toggleCols(id)}
        onClean={setCleanTarget}
        onReDerive={id => void reDerive(id)}
      />

      {/* NL data-cleaning modal (C24) — opened from a uploaded row's Clean button. */}
      <CleanModal
        datasetId={cleanTarget?.id ?? null}
        filename={cleanTarget?.filename ?? null}
        open={cleanTarget !== null}
        onClose={() => setCleanTarget(null)}
        onApplied={() => {
          setCleanTarget(null)
          void load()
        }}
      />
    </>
  )
}


