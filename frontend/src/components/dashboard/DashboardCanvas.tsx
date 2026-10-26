'use client'

import { useState, type CSSProperties } from 'react'
import type { DashboardData, DashboardRecord, DashboardWidget } from '@/lib/api'
import { announce } from '@/lib/announce'
import {
  WIDTH_PRESETS,
  moveWidget,
  moveWidgetBy,
  orderedByPosition,
  positionOf,
  setWidth,
} from '@/lib/dashboardLayout'
import { ChartWidget } from './ChartWidget'
import { FieldsPanelStub } from './FieldsPanelStub'
import { KpiWidget } from './KpiWidget'
import { TableWidget } from './TableWidget'

export type SaveState = 'idle' | 'saving' | 'saved' | 'error'

const STUB_TIP = 'Coming in a later phase'

/**
 * Canvas: header (title / command / save pill / badges / stubs) + the 12-column
 * widget grid with native HTML5 drag-and-drop and a keyboard alternative.
 * Presentational: layout changes are reported via `onLayoutChange` (the tab
 * applies them optimistically, PATCHes once, and reverts on failure).
 */
export function DashboardCanvas({
  record,
  data,
  dataError,
  saveState,
  saveMessage,
  onLayoutChange,
  onRetrySave,
  onRename,
}: {
  record: DashboardRecord
  data: DashboardData | null
  dataError: string | null
  saveState: SaveState
  saveMessage: string | null
  onLayoutChange: (widgets: DashboardWidget[]) => void
  onRetrySave: () => void
  onRename: (title: string) => Promise<void>
}) {
  const widgets = record.spec.widgets
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)

  const gen = record.generation
  const ordered = orderedByPosition(widgets)

  const commitRename = async () => {
    const next = draft.trim()
    setEditing(false)
    if (!next || next === record.title) return
    try {
      setRenameError(null)
      await onRename(next.slice(0, 80))
    } catch {
      setRenameError("Couldn't rename the dashboard.")
    }
  }

  const keyMove = (e: React.KeyboardEvent, w: DashboardWidget) => {
    let delta = 0
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') delta = -1
    else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') delta = 1
    if (delta === 0) return
    e.preventDefault()
    const next = moveWidgetBy(widgets, w.id, delta)
    if (next.every((n, i) => n === widgets[i])) return
    onLayoutChange(next)
    announce(`Moved ${w.title} to position ${positionOf(next, w.id)} of ${next.length}`)
  }

  const pill =
    saveState === 'saving'
      ? { text: 'Saving…', cls: 'border-gray-200 bg-gray-50 text-gray-600' }
      : saveState === 'error'
        ? { text: 'Couldn’t save — retry', cls: 'border-red-200 bg-red-50 text-red-700' }
        : saveState === 'saved'
          ? { text: 'Layout saved ✓', cls: 'border-green-200 bg-green-50 text-green-700' }
          : null

  return (
    <div>
      <header className="mb-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {editing ? (
              <input
                autoFocus
                value={draft}
                maxLength={80}
                aria-label="Dashboard title"
                onChange={e => setDraft(e.target.value)}
                onBlur={() => void commitRename()}
                onKeyDown={e => {
                  if (e.key === 'Enter') e.currentTarget.blur()
                  if (e.key === 'Escape') setEditing(false)
                }}
                className="w-full rounded-md border border-indigo-400 px-2 py-1 text-lg font-semibold text-gray-900"
              />
            ) : (
              <h2 className="text-lg font-semibold text-gray-900">
                <button
                  type="button"
                  title="Click to rename"
                  onClick={() => {
                    setDraft(record.title)
                    setEditing(true)
                  }}
                  className="rounded px-1 text-left hover:bg-gray-100"
                >
                  {record.title}
                </button>
              </h2>
            )}
            <p className="mt-0.5 truncate px-1 text-xs text-gray-500" title={record.command}>
              “{record.command}” · {record.dataset_filename}
            </p>
            {renameError && (
              <p role="alert" className="px-1 text-xs text-red-700">
                {renameError}
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {pill && (
              <span
                role="status"
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${pill.cls}`}
                title={saveState === 'error' ? (saveMessage ?? undefined) : undefined}
              >
                {pill.text}
                {saveState === 'error' && (
                  <button type="button" onClick={onRetrySave} className="underline">
                    Retry
                  </button>
                )}
              </span>
            )}
            {(['+ Add widget', 'Export', 'Regenerate'] as const).map(label => (
              <button
                key={label}
                type="button"
                disabled
                title={STUB_TIP}
                aria-label={`${label} — ${STUB_TIP.toLowerCase()}`}
                className="cursor-not-allowed rounded-md border border-dashed border-gray-300 px-2.5 py-1 text-xs text-gray-400"
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {gen.used_fallback && (
          <p className="mt-3 inline-block rounded-md border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800">
            Automatic dashboard — the AI response couldn’t be used
          </p>
        )}
        {gen.dropped_widgets.length > 0 && (
          <details className="mt-2 text-xs text-gray-600">
            <summary className="cursor-pointer">
              {gen.dropped_widgets.length} suggested widget{gen.dropped_widgets.length === 1 ? ' was' : 's were'} skipped
            </summary>
            <ul className="mt-1 list-disc pl-5">
              {gen.dropped_widgets.map((d, i) => (
                <li key={i}>
                  {d.title}: {d.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </header>

      {dataError && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {dataError}
        </p>
      )}

      <div className="dash-grid" role="list" aria-label="Dashboard widgets">
        {ordered.map((w, i) => {
          const l = w.layout
          const style = {
            '--gc': `${l.x + 1} / span ${l.w}`,
            '--gr': `${l.y + 1} / span ${l.h}`,
            '--gh': l.h,
          } as CSSProperties
          const wd = data?.widgets[w.id]
          const dropTarget = overId === w.id && dragId !== null && dragId !== w.id
          return (
            <article
              key={w.id}
              role="listitem"
              style={style}
              data-widget-id={w.id}
              onDragOver={e => {
                if (!dragId) return
                e.preventDefault()
                e.dataTransfer.dropEffect = 'move'
                if (overId !== w.id) setOverId(w.id)
              }}
              onDragLeave={() => setOverId(cur => (cur === w.id ? null : cur))}
              onDrop={e => {
                e.preventDefault()
                const from = dragId
                setDragId(null)
                setOverId(null)
                if (!from || from === w.id) return
                const next = moveWidget(widgets, from, w.id)
                if (next.every((n, idx) => n === widgets[idx])) return
                onLayoutChange(next)
                const moved = widgets.find(x => x.id === from)
                if (moved) announce(`Moved ${moved.title} to position ${positionOf(next, from)} of ${next.length}`)
              }}
              className={`dash-widget flex min-h-0 flex-col overflow-hidden rounded-lg border bg-white shadow-sm ${
                dropTarget ? 'border-indigo-500 outline outline-2 outline-indigo-400' : 'border-gray-200'
              } ${dragId === w.id ? 'opacity-50' : ''}`}
            >
              <div className="flex items-center gap-2 border-b border-gray-100 px-2 py-1.5">
                <span
                  role="button"
                  tabIndex={0}
                  draggable
                  aria-label={`Move widget: ${w.title}`}
                  title="Drag to move, or focus and use the arrow keys"
                  onDragStart={e => {
                    setDragId(w.id)
                    e.dataTransfer.effectAllowed = 'move'
                    e.dataTransfer.setData('text/plain', w.id)
                    const card = e.currentTarget.closest('article')
                    if (card) e.dataTransfer.setDragImage(card, 16, 16)
                  }}
                  onDragEnd={() => {
                    setDragId(null)
                    setOverId(null)
                  }}
                  onKeyDown={e => keyMove(e, w)}
                  className="cursor-grab select-none rounded px-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 active:cursor-grabbing"
                >
                  ⠿
                </span>
                <h3 className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800" title={w.title}>
                  {w.title}
                </h3>
                <div role="group" aria-label={`Width of ${w.title}`} className="flex overflow-hidden rounded border border-gray-200">
                  {(Object.keys(WIDTH_PRESETS) as (keyof typeof WIDTH_PRESETS)[]).map(k => {
                    const active = l.w === WIDTH_PRESETS[k]
                    return (
                      <button
                        key={k}
                        type="button"
                        aria-pressed={active}
                        title={`Width ${k}`}
                        onClick={() => {
                          if (!active) onLayoutChange(setWidth(widgets, w.id, WIDTH_PRESETS[k]))
                        }}
                        className={`px-1.5 text-[11px] font-medium ${
                          active ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-50'
                        }`}
                      >
                        {k}
                      </button>
                    )
                  })}
                </div>
                <button
                  type="button"
                  disabled
                  title={STUB_TIP}
                  aria-label={`Edit widget — ${STUB_TIP.toLowerCase()}`}
                  className="cursor-not-allowed rounded px-1 text-gray-300"
                >
                  ⋯
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-auto p-2">
                {w.kind === 'kpi' && <KpiWidget def={w} data={wd} />}
                {w.kind === 'chart' && <ChartWidget def={w} data={wd} index={i} />}
                {w.kind === 'table' && <TableWidget data={wd} />}
              </div>
            </article>
          )
        })}
      </div>

      <div className="mt-3">
        <FieldsPanelStub datasetId={record.dataset_id} />
      </div>
    </div>
  )
}
