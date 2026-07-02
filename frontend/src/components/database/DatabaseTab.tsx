'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type DatasetSummary } from '@/lib/api'
import { ERDiagramPanel, type ErDataset } from '@/components/database/ERDiagramPanel'
import { TableDescriptionPanel } from '@/components/database/TableDescriptionPanel'
import { ConnectDatabaseCard } from '@/components/database/ConnectDatabaseCard'
import { TablesCard } from '@/components/analyse/TablesCard'
import { UploadCard } from '@/components/analyse/UploadCard'

/**
 * Database tab — REAL (Phase 4), 3-column layout (v0.6 follow-up).
 *
 * Fetches the data universe (`GET /datasets`) and renders three columns:
 * Upload + Tables (left, collapsible) · the schema ER diagram (middle, always
 * visible) · the per-dataset `<TableDescriptionPanel>` (right, collapsible).
 * The diagram and the description panel share one `selectedId` so clicking a
 * table card drives the right-hand detail view; the left column's Tables list
 * shares the same dataset universe and a separate `selectedDatasetIds` used
 * only for its own bulk-delete action.
 *
 * The list is fetched on mount (the tab re-mounts when shown, so this is also
 * the "re-fetch when the tab is shown" hook) and re-fetched after any mutation
 * (upload / clean / re-derive / delete / clear-database) via a bumped refresh
 * token — also passed to `<TablesCard>` as its own `datasetsVersion`. The
 * header shows the uploaded/derived counts, the two column-visibility toggle
 * chips, and a REAL danger "Clear database" action behind an inline confirm
 * that calls `DELETE /datasets`.
 */
export function DatabaseTab() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // Left column (Upload + Tables) and right column (description) each
  // collapse independently to give the diagram more width. Left defaults
  // open (this is where data enters); the description defaults collapsed.
  const [leftOpen, setLeftOpen] = useState(true)
  const [descOpen, setDescOpen] = useState(false)
  // Tables list's own row-selection, for its bulk-delete action only.
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([])

  const [confirmClear, setConfirmClear] = useState(false)
  const [clearing, setClearing] = useState(false)

  // C36 (Phase 9, BETA) — the "Connect a database" affordance is fully absent
  // (not collapsed/disabled) unless the backend reports the flag on. Fetched
  // once on mount; a flag flip requires a page reload to take effect, which
  // matches the flag's own env-var-at-startup semantics.
  const [connectorsEnabled, setConnectorsEnabled] = useState(false)

  // Bumped after a child mutation so the list (and counts) re-fetch.
  const [refreshToken, setRefreshToken] = useState(0)
  const refresh = useCallback(() => setRefreshToken(t => t + 1), [])

  const toggleSelect = useCallback((id: string) => {
    setSelectedDatasetIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id],
    )
  }, [])
  const selectAll = useCallback((ids: string[]) => setSelectedDatasetIds(ids), [])
  const clearSelection = useCallback(() => setSelectedDatasetIds([]), [])

  // Shared by both TablesCard and TableDescriptionPanel — either can delete
  // the currently-selected dataset, so both drop it from every piece of
  // local state (the list, the row-selection, and the ERD/description focus).
  const handleDatasetDeleted = useCallback(
    (id: string) => {
      setDatasets(prev => prev.filter(d => d.id !== id))
      setSelectedDatasetIds(prev => prev.filter(x => x !== id))
      setSelectedId(prev => (prev === id ? null : prev))
      refresh()
    },
    [refresh],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await api.listDatasets()
      setDatasets(Array.isArray(list) ? list : [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the database.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  // C36 — fetch the BETA flag once on mount. Always 200 (never gated), so a
  // failure here is swallowed and the affordance simply stays hidden — this
  // is a hidden-by-default BETA feature, not a user-facing error surface.
  useEffect(() => {
    let cancelled = false
    api
      .connections.status()
      .then(res => {
        if (!cancelled) setConnectorsEnabled(res.enabled === true)
      })
      .catch(() => {
        if (!cancelled) setConnectorsEnabled(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Keep the selection valid as the universe changes: default to the first
  // dataset, and drop a selection whose dataset was deleted.
  useEffect(() => {
    if (datasets.length === 0) {
      if (selectedId !== null) setSelectedId(null)
      return
    }
    if (selectedId === null || !datasets.some(d => d.id === selectedId)) {
      setSelectedId(datasets[0].id)
    }
  }, [datasets, selectedId])

  const uploadedCount = useMemo(
    () => datasets.filter(d => d.origin !== 'derived').length,
    [datasets],
  )
  const derivedCount = useMemo(
    () => datasets.filter(d => d.origin === 'derived').length,
    [datasets],
  )

  const doClear = useCallback(async () => {
    setClearing(true)
    setError(null)
    try {
      await api.clearAllDatasets()
      setConfirmClear(false)
      setSelectedId(null)
      setDatasets([])
      refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear the database.')
    } finally {
      setClearing(false)
    }
  }, [refresh])

  // The diagram + badges need column metadata; `GET /datasets` carries `columns`.
  const erDatasets = datasets as ErDataset[]
  const isEmpty = !loading && !error && datasets.length === 0

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <h2 className="text-sm font-semibold text-gray-800">Database</h2>
          <p className="text-xs text-gray-500 tabular-nums">
            {loading && datasets.length === 0
              ? 'Loading…'
              : `${datasets.length} dataset${datasets.length === 1 ? '' : 's'} · ${uploadedCount} uploaded · ${derivedCount} derived`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Column-visibility is now toggled via each panel's own inline
              "Hide"/edge tab (see the middle column below) — no header
              chips needed. */}
          {confirmClear ? (
            <span className="inline-flex items-center gap-2">
              <span className="text-xs text-gray-600">
                Delete ALL datasets and sessions?
              </span>
              <button
                type="button"
                onClick={() => void doClear()}
                disabled={clearing}
                className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {clearing && <Spinner />}
                {clearing ? 'Clearing…' : 'Yes, clear'}
              </button>
              <button
                type="button"
                onClick={() => setConfirmClear(false)}
                disabled={clearing}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmClear(true)}
              disabled={datasets.length === 0}
              title={
                datasets.length === 0
                  ? 'No datasets to clear'
                  : 'Delete every dataset, derived set, query, and session'
              }
              className="rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:border-gray-200 disabled:bg-gray-50 disabled:text-gray-300"
            >
              Clear database
            </button>
          )}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded border border-red-300 bg-white px-2 py-0.5 font-medium text-red-700 hover:bg-red-100"
          >
            Retry
          </button>
        </div>
      )}

      {/* 3-column layout: Upload+Tables (left, collapsible) · the ER diagram
          (middle, always mounted — its own empty state replaces just this
          column when there's no data) · the description panel (right,
          collapsible, never shown while empty). Side tracks are a FIXED width
          so neither the diagram nor a re-selected table shifts the layout;
          `min-w-0` lets each column's overflow (staged uploads, the wide SVG,
          the data preview) scroll inside its own track instead of stretching
          it. Column templates are enumerated as literal strings — Tailwind's
          JIT can't see a runtime-built arbitrary value. */}
      <div
        className={`grid grid-cols-1 gap-4 ${
          isEmpty
            ? leftOpen
              ? 'lg:grid-cols-[24rem_minmax(0,1fr)]'
              : 'lg:grid-cols-1'
            : leftOpen && descOpen
              ? 'lg:grid-cols-[24rem_minmax(0,1fr)_24rem]'
              : leftOpen
                ? 'lg:grid-cols-[24rem_minmax(0,1fr)]'
                : descOpen
                  ? 'lg:grid-cols-[minmax(0,1fr)_24rem]'
                  : 'lg:grid-cols-1'
        }`}
      >
        {leftOpen && (
          <div className="min-w-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto">
            {/* left-column-stack: merges UploadCard + TablesCard's own
                bordered/shadowed <section>s into one continuous card (see the
                `.left-column-stack > section` rules in globals.css) — matching
                the single-card look of the Table description panel. Collapsing
                this column is handled by the accent edge-tab on the diagram's
                left border (see the middle column), so there's no in-card Hide
                button and no edit to UploadCard's synced source. */}
            <div className="left-column-stack flex flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
              <UploadCard onUploaded={refresh} />
              <TablesCard
                datasetsVersion={refreshToken}
                selectedDatasetIds={selectedDatasetIds}
                onToggleSelect={toggleSelect}
                onSelectAll={selectAll}
                onClearSelection={clearSelection}
                onDeleted={handleDatasetDeleted}
              />
              {/* C36 (Phase 9, BETA) — fully absent unless the backend flag
                  is on; never rendered collapsed/disabled. Imported tables
                  become ordinary datasets, so the same `refresh()` used after
                  an upload picks them up in the Tables list above. */}
              {connectorsEnabled && <ConnectDatabaseCard onImported={refresh} />}
            </div>
          </div>
        )}

        {/* lg:self-start so this wrapper hugs the Schema pane's height instead
            of stretching to the full (taller) grid-row height — otherwise the
            edge tabs' top-1/2 would center on the row (≈ the side panels) rather
            than on the Schema pane itself. */}
        <div className="relative min-w-0 lg:self-start">
          {/* Edge toggle tabs — one per collapsible side column, docked to this
              (always-mounted, non-scrolling) middle column's corners, vertically
              centered on the Schema pane and half-overlapping its border. Solid accent color
              (bg-blue-600 → var(--accent-solid), same remap the rest of the
              app's primary actions use) so they read as an inviting handle. Each
              toggles its side open/closed and the chevron points toward that
              side's panel; these are the SINGLE collapse+expand control for each
              side, replacing the old in-card / in-panel gray "Hide" buttons. */}
          <button
            type="button"
            onClick={() => setLeftOpen(o => !o)}
            aria-label={leftOpen ? 'Hide upload and tables' : 'Show upload and tables'}
            title={leftOpen ? 'Hide upload and tables' : 'Show upload and tables'}
            className="absolute -left-3 top-1/2 z-10 flex h-20 w-7 -translate-y-1/2 items-center justify-center rounded-md bg-blue-600 text-lg text-white shadow-md hover:bg-blue-700"
          >
            {leftOpen ? '‹' : '›'}
          </button>
          {!isEmpty && (
            <button
              type="button"
              onClick={() => setDescOpen(o => !o)}
              aria-label={descOpen ? 'Hide table description' : 'Show table description'}
              title={descOpen ? 'Hide table description' : 'Show table description'}
              className="absolute -right-3 top-1/2 z-10 flex h-20 w-7 -translate-y-1/2 items-center justify-center rounded-md bg-blue-600 text-lg text-white shadow-md hover:bg-blue-700"
            >
              {descOpen ? '›' : '‹'}
            </button>
          )}

          {isEmpty ? (
            <div className="flex flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-gray-200 bg-white px-4 py-16 text-center">
              <span aria-hidden="true" className="mb-1 text-3xl text-gray-300">
                ⬚
              </span>
              <p className="text-sm font-medium text-gray-500">No datasets yet</p>
              <p className="text-xs text-gray-400">
                Upload a CSV using the panel on the left — its schema and details
                appear here.
              </p>
            </div>
          ) : (
            <ERDiagramPanel datasets={erDatasets} selectedId={selectedId} onSelect={setSelectedId} />
          )}
        </div>

        {descOpen && !isEmpty && (
          <div className="min-w-0">
            {/* No onCollapse — collapsing is handled by the accent edge-tab on
                the diagram's right border, so the panel's own built-in "Hide ›"
                (gated on onCollapse) stays hidden and the two sides match. */}
            <TableDescriptionPanel
              datasetId={selectedId}
              allDatasets={erDatasets}
              onChanged={refresh}
              onDeleted={handleDatasetDeleted}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  )
}

