'use client'

import { useEffect, useState } from 'react'
import { api, type ColumnSchema } from '@/lib/api'

/**
 * LABELLED STUB (Phase 16+): the dataset's columns as non-draggable chips with a
 * visible "coming in a later phase" tag. Collapsed by default.
 */
export function FieldsPanelStub({ datasetId }: { datasetId: string }) {
  const [open, setOpen] = useState(false)
  const [columns, setColumns] = useState<ColumnSchema[] | null>(null)

  useEffect(() => {
    if (!open || columns) return
    let cancelled = false
    api
      .getDataset(datasetId)
      .then(d => {
        if (!cancelled) setColumns(d.columns_schema ?? [])
      })
      .catch(() => {
        if (!cancelled) setColumns([])
      })
    return () => {
      cancelled = true
    }
  }, [open, columns, datasetId])

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between text-sm font-semibold text-gray-700"
      >
        <span>Fields</span>
        <span aria-hidden="true" className="text-xs text-gray-400">{open ? '▾' : '▸'}</span>
      </button>
      <p className="mt-1 inline-block rounded bg-yellow-100 px-2 py-0.5 text-[11px] font-medium text-yellow-900">
        Drag fields onto widgets to reconfigure — coming in a later phase
      </p>
      {open && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {columns === null && <span className="text-xs text-gray-400">Loading fields…</span>}
          {columns?.length === 0 && <span className="text-xs text-gray-400">No fields to show.</span>}
          {columns?.map(c => (
            <span
              key={c.name}
              aria-disabled="true"
              title="Coming in a later phase"
              className="inline-flex cursor-not-allowed items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-500"
            >
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
              {c.name}
              <span className="text-[10px] text-gray-400">{c.dtype}</span>
            </span>
          ))}
        </div>
      )}
    </section>
  )
}
