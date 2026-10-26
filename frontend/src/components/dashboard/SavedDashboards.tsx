'use client'

import { useState } from 'react'
import type { DashboardSummary } from '@/lib/api'

function relativeTime(iso: string): string {
  const hasZone = iso.endsWith('Z') || /[+-]\d\d:?\d\d$/.test(iso)
  const t = Date.parse(hasZone ? iso : `${iso}Z`)
  if (Number.isNaN(t)) return ''
  const s = Math.max(0, Math.round((Date.now() - t) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

/** Saved dashboards list: open on click, trash icon with inline confirm. */
export function SavedDashboards({
  items,
  loading,
  error,
  activeId,
  onOpen,
  onDelete,
}: {
  items: DashboardSummary[]
  loading: boolean
  error: string | null
  activeId: string | null
  onOpen: (id: string) => void
  onDelete: (id: string) => Promise<void>
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  return (
    <section
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      aria-labelledby="dash-saved-h"
    >
      <h2 id="dash-saved-h" className="text-sm font-semibold text-gray-800">
        Saved dashboards
      </h2>
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-700">
          {error}
        </p>
      )}
      {loading && items.length === 0 && <p className="mt-2 text-xs text-gray-400">Loading…</p>}
      {!loading && !error && items.length === 0 && (
        <p className="mt-2 text-xs text-gray-500">
          Pick a dataset, describe the dashboard you want, press Build.
        </p>
      )}
      <ul className="mt-2 space-y-1.5">
        {items.map(d => (
          <li
            key={d.id}
            className={`rounded-md border px-2 py-1.5 ${
              d.id === activeId ? 'border-indigo-400 bg-indigo-50' : 'border-gray-200 bg-white'
            }`}
          >
            {confirmId === d.id ? (
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-gray-700">Delete “{d.title}”?</span>
                <span className="flex gap-1.5">
                  <button
                    type="button"
                    disabled={busyId === d.id}
                    onClick={() => {
                      setBusyId(d.id)
                      void onDelete(d.id).finally(() => {
                        setBusyId(null)
                        setConfirmId(null)
                      })
                    }}
                    className="rounded bg-red-600 px-2 py-0.5 font-medium text-white hover:bg-red-700 disabled:opacity-60"
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmId(null)}
                    className="rounded border border-gray-300 px-2 py-0.5 text-gray-600 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </span>
              </div>
            ) : (
              <div className="flex items-start gap-2">
                <button
                  type="button"
                  onClick={() => onOpen(d.id)}
                  aria-current={d.id === activeId ? 'true' : undefined}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="truncate text-sm font-medium text-gray-800">{d.title}</div>
                  <div className="truncate text-[11px] text-gray-500">
                    {d.dataset_filename} · {d.widget_count} widget{d.widget_count === 1 ? '' : 's'} ·{' '}
                    {relativeTime(d.updated_at)}
                  </div>
                </button>
                <button
                  type="button"
                  aria-label={`Delete dashboard: ${d.title}`}
                  title="Delete dashboard"
                  onClick={() => setConfirmId(d.id)}
                  className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-red-600"
                >
                  <span aria-hidden="true">🗑</span>
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
