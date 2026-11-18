'use client'

import { useState } from 'react'
import type { DashboardWidget } from '@/lib/api'
import { announce } from '@/lib/announce'
import { reorderPriority, reorderPriorityBy, sortByPriority } from '@/lib/dashboardPriority'

/**
 * "Priority" popover (C41): a numbered list of every widget, reordered by drag
 * handle or Up/Down buttons. Nothing is sent until Save order; a failed save
 * keeps the panel open with the error so the draft isn't lost.
 */
export function PriorityPanel({
  widgets,
  onSave,
}: {
  widgets: DashboardWidget[]
  onSave: (order: string[], rearrange: boolean) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [order, setOrder] = useState<string[]>([])
  const [rearrange, setRearrange] = useState(true)
  const [dragId, setDragId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const byId = new Map(widgets.map(w => [w.id, w]))
  // The priority helpers read a rank per widget; the draft's rank is its position.
  const draft = order.map((id, i) => ({ id, kind: byId.get(id)?.kind ?? 'kpi', priority: i + 1 }))

  const toggle = () => {
    if (!open) {
      setOrder(sortByPriority(widgets).map(w => w.id))
      setError(null)
    }
    setOpen(!open)
  }

  const shift = (id: string, delta: number) => {
    const next = reorderPriorityBy(draft, id, delta)
    setOrder(next)
    announce(`${byId.get(id)?.title ?? 'Widget'} is now priority ${next.indexOf(id) + 1} of ${next.length}`)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await onSave(order, rearrange)
      setOpen(false)
      announce('Priority order saved')
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the priority order.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="relative"
      onKeyDown={e => {
        if (e.key === 'Escape' && open) setOpen(false)
      }}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={toggle}
        className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
      >
        Priority
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Reorder widget priority"
          className="absolute right-0 z-20 mt-1 w-80 rounded-lg border border-gray-200 bg-white p-3 shadow-lg"
        >
          <p className="mb-2 text-xs text-gray-500">Most important first. The top KPIs become Key insights.</p>
          <ol className="max-h-80 space-y-1 overflow-auto">
            {draft.map((item, i) => {
              const w = byId.get(item.id)
              if (!w) return null
              return (
                <li
                  key={item.id}
                  onDragOver={e => {
                    if (dragId) e.preventDefault()
                  }}
                  onDrop={e => {
                    e.preventDefault()
                    if (dragId) setOrder(reorderPriority(draft, dragId, item.id))
                    setDragId(null)
                  }}
                  className={`flex items-center gap-1.5 rounded border px-1.5 py-1 text-xs ${
                    dragId === item.id ? 'border-indigo-300 opacity-50' : 'border-gray-200'
                  }`}
                >
                  <span
                    draggable
                    aria-hidden="true"
                    onDragStart={e => {
                      setDragId(item.id)
                      e.dataTransfer.effectAllowed = 'move'
                      e.dataTransfer.setData('text/plain', item.id)
                    }}
                    onDragEnd={() => setDragId(null)}
                    className="cursor-grab select-none text-gray-400 active:cursor-grabbing"
                  >
                    ⠿
                  </span>
                  <span className="w-5 shrink-0 text-right font-semibold tabular-nums text-gray-500">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate text-gray-800" title={w.title}>
                    {w.title}
                  </span>
                  <span className="shrink-0 text-[10px] uppercase text-gray-400">{w.kind}</span>
                  <button
                    type="button"
                    disabled={i === 0}
                    aria-label={`Move ${w.title} up`}
                    onClick={() => shift(item.id, -1)}
                    className="rounded px-1 text-gray-500 hover:bg-gray-100 disabled:text-gray-300"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    disabled={i === draft.length - 1}
                    aria-label={`Move ${w.title} down`}
                    onClick={() => shift(item.id, 1)}
                    className="rounded px-1 text-gray-500 hover:bg-gray-100 disabled:text-gray-300"
                  >
                    ↓
                  </button>
                </li>
              )
            })}
          </ol>
          <label className="mt-2 flex items-center gap-1.5 text-xs text-gray-600">
            <input type="checkbox" checked={rearrange} onChange={e => setRearrange(e.target.checked)} />
            Re-arrange layout to match
          </label>
          {error && (
            <p role="alert" className="mt-2 text-xs text-red-700">
              {error}
            </p>
          )}
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => void save()}
              className="rounded-md bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Save order'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
