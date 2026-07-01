'use client'

import { useCallback, useEffect, useState } from 'react'
import { api, type Session } from '@/lib/api'

/**
 * Sessions sidebar (C9) — REAL in Phase 3.
 *
 * Lists sessions from GET /sessions (most-recently-updated first), each showing
 * its name (or `first_question` as a fallback label) and turn count. Supports:
 *  - **+New**  — clears the active conversation; the next /ask with no
 *    session_id creates the session server-side (the parent adopts the returned
 *    session_id and refreshes the list).
 *  - **Resume** — click a session → the parent loads GET /sessions/{id}.
 *  - **Rename** — inline edit → PATCH /sessions/{id}/name → refresh.
 *  - **Delete** — per-session → DELETE /sessions/{id} → refresh (the parent
 *    clears the conversation if the active session was deleted).
 *  - **Checkbox** — per-row checkbox to select sessions for bulk delete.
 *  - **Select all / Deselect all** — header toggle (visible when sessions exist).
 *  - **Delete selected (N)** — bulk-delete via DELETE /sessions with body
 *    {session_ids:[...]}; visible when ≥1 checkbox is ticked.
 *  - **Clear all** — DELETE /sessions behind a confirm → refresh.
 *  - **Project notes** — opens the global-memory modal.
 *
 * The list refreshes whenever `refreshToken` changes (the parent bumps it after
 * each completed ask so turn counts / ordering update). All states (loading,
 * error, empty, list) render explicitly so a failure never blanks the panel.
 *
 * This module is split container/presentational:
 *  - `SessionSidebarView` — PURE presentation. Receives the session list, the
 *    active id, busy/error flags, and `on*` callbacks; owns only purely-local
 *    UI state (the rename text field, the per-row checkbox selection, and the
 *    inline confirm toggles). It performs NO data loading or `api.*` calls.
 *  - `SessionSidebar` — thin CONTAINER. Owns all `useEffect`/`api.*`/data state
 *    and renders `<SessionSidebarView ... />`.
 */

export interface SessionSidebarViewProps {
  /** Sessions to render (most-recently-updated first). */
  sessions: Session[]
  /** The currently-active session id, or null. */
  activeSessionId: string | null
  /** True while the initial list is loading and no sessions are shown yet. */
  loading: boolean
  /** A load/CRUD error message to display, or null. */
  error: string | null
  /** Id of the session currently mid-flight for rename/delete, or null. */
  busyId: string | null
  /** True while a bulk-delete request is in flight. */
  bulkDeleting: boolean
  /** True while the clear-all request is in flight. */
  clearingAll: boolean
  /** Resume (open) the session with this id. */
  onResume: (id: string) => void
  /** Start a fresh conversation. */
  onNew: () => void
  /** Open the project-notes / global-memory modal. */
  onOpenMemory: () => void
  /** Retry loading the list after an error. */
  onRetry: () => void
  /** Commit a rename for `id` to `name` (already trimmed, non-empty). */
  onRename: (id: string, name: string) => void
  /** Delete the single session with this id. */
  onDelete: (id: string) => void
  /** Clear (delete) all sessions. */
  onClearAll: () => void
  /** Bulk-delete the given session ids. */
  onBulkDelete: (ids: string[]) => void
}

/**
 * Format an ISO timestamp as a compact local date-time (e.g. "Jun 30 3:05 PM"),
 * or null if absent/invalid. Omits the year and the date/time comma to keep the
 * "Started … · upd …" line short enough to fit on one row.
 */
function fmtTime(iso?: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d.getTime())) return null
  const date = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${date} ${time}`
}

/**
 * PURE presentational sidebar. Renders entirely from props; the only state it
 * keeps is local UI affordance state (rename text, checkbox selection, inline
 * confirm toggles) that is not application data.
 */
export function SessionSidebarView({
  sessions,
  activeSessionId,
  loading,
  error,
  busyId,
  bulkDeleting,
  clearingAll,
  onResume,
  onNew,
  onOpenMemory,
  onRetry,
  onRename,
  onDelete,
  onClearAll,
  onBulkDelete,
}: SessionSidebarViewProps) {
  // Purely-local UI state (not application data).
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [confirmClearAll, setConfirmClearAll] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Clear selection whenever the session list changes (e.g. after a delete/refresh).
  useEffect(() => {
    setSelected(new Set())
  }, [sessions])

  const startRename = useCallback((s: Session) => {
    setRenamingId(s.id)
    setRenameValue(s.name ?? s.first_question ?? '')
  }, [])

  const commitRename = useCallback(
    (id: string) => {
      const name = renameValue.trim()
      if (!name) {
        setRenamingId(null)
        return
      }
      setRenamingId(null)
      onRename(id, name)
    },
    [renameValue, onRename],
  )

  // Toggle one checkbox.
  const toggleSelect = useCallback((id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  // Select all / deselect all.
  const allSelected = sessions.length > 0 && sessions.every(s => selected.has(s.id))
  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(sessions.map(s => s.id)))
    }
  }, [allSelected, sessions])

  const doBulkDelete = useCallback(() => {
    const ids = [...selected]
    if (ids.length === 0) return
    onBulkDelete(ids)
  }, [selected, onBulkDelete])

  return (
    <section
      aria-labelledby="sessions-heading"
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 id="sessions-heading" className="text-base font-semibold text-gray-900">
          📋 Sessions
        </h2>
        <button
          type="button"
          onClick={onOpenMemory}
          className="project-notes-btn rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 transition-colors"
        >
          Project notes
        </button>
      </div>

      {/* Action bar: +New, Select all/Deselect all, Delete selected, Clear all */}
      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onNew}
          className="rounded-lg border border-emerald-200 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-50 transition-colors"
        >
          + New
        </button>

        {/* Select all / Deselect all — only visible when sessions exist */}
        {sessions.length > 0 && (
          <button
            type="button"
            onClick={toggleSelectAll}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            {allSelected ? 'Deselect all' : 'Select all'}
          </button>
        )}

        {/* Delete selected — visible when ≥1 checkbox is ticked */}
        {selected.size > 0 && (
          <button
            type="button"
            onClick={doBulkDelete}
            disabled={bulkDeleting}
            className="rounded-lg border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-rose-100 disabled:opacity-60 transition-colors"
          >
            {bulkDeleting ? 'Deleting…' : `Delete selected (${selected.size})`}
          </button>
        )}

        {sessions.length > 0 &&
          (confirmClearAll ? (
            <span className="inline-flex items-center gap-1">
              <span className="text-xs text-gray-600">Clear all?</span>
              <button
                type="button"
                onClick={onClearAll}
                disabled={clearingAll}
                className="rounded-lg border border-red-300 bg-red-50 px-2 py-1 text-xs font-medium text-red-700 hover:bg-rose-100 disabled:opacity-60 transition-colors"
              >
                {clearingAll ? 'Clearing…' : 'Yes'}
              </button>
              <button
                type="button"
                onClick={() => setConfirmClearAll(false)}
                className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
              >
                No
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmClearAll(true)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors"
            >
              Clear all
            </button>
          ))}
      </div>

      {loading && sessions.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 px-3 py-6 text-center text-xs text-gray-400">
          Loading sessions…
        </div>
      ) : error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-2 rounded-lg border border-rose-200 bg-red-50 px-3 py-5 text-center text-xs text-red-700"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={onRetry}
            className="rounded-lg border border-red-300 bg-white px-2 py-0.5 font-medium text-red-700 hover:bg-rose-100 transition-colors"
          >
            Retry
          </button>
        </div>
      ) : sessions.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 px-3 py-6 text-center text-xs text-gray-400">
          No sessions yet. Ask a question to start one.
        </div>
      ) : (
        <ul role="list" className="max-h-[20rem] space-y-0.5 overflow-y-auto pr-1">
          {sessions.map(s => {
            const active = activeSessionId === s.id
            const label = s.name?.trim() || s.first_question?.trim() || 'Untitled session'
            const isSelected = selected.has(s.id)
            return (
              <li
                key={s.id}
                className={`rounded-md border px-2 py-0.5 transition-colors ${
                  active ? 'border-green-400 bg-green-50' : 'border-gray-200 hover:bg-gray-50'
                }`}
              >
                {renamingId === s.id ? (
                  <div className="flex items-center gap-2">
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={e => setRenameValue(e.target.value)}
                      onClick={e => e.stopPropagation()}
                      onKeyDown={e => {
                        e.stopPropagation()
                        if (e.key === 'Enter') commitRename(s.id)
                        if (e.key === 'Escape') setRenamingId(null)
                      }}
                      aria-label={`Rename session ${label}`}
                      className="min-w-0 flex-1 rounded-lg border border-gray-300 px-2 py-1 text-xs focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    />
                    <button
                      type="button"
                      onClick={() => commitRename(s.id)}
                      disabled={busyId === s.id}
                      className="rounded-lg border border-green-400 bg-green-50 px-2 py-1 text-[11px] font-medium text-green-700 hover:bg-green-50 disabled:opacity-60 transition-colors"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setRenamingId(null)}
                      className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-[11px] font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => onResume(s.id)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onResume(s.id)
                      }
                    }}
                    aria-label={`Resume session ${label}`}
                    className="cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-indigo-400 rounded"
                  >
                    {/* Row 1: checkbox + label (click to resume) */}
                    <div className="flex items-center gap-2">
                      {/* Checkbox — stops propagation so row-click (resume) is not triggered */}
                      <input
                        type="checkbox"
                        checked={isSelected}
                        aria-label={`Select session ${label}`}
                        onChange={() => toggleSelect(s.id)}
                        onClick={e => e.stopPropagation()}
                        className="h-3.5 w-3.5 flex-shrink-0 cursor-pointer rounded border-gray-300 accent-green-600"
                      />
                      <span className="block min-w-0 flex-1 truncate text-left text-sm font-medium text-gray-900">
                        {label}
                      </span>
                    </div>

                    {/* Row 2: meta + actions, all on one compact line */}
                    <div className="flex items-center gap-2 pl-[1.375rem] text-[11px]">
                      <span className="whitespace-nowrap text-gray-500">
                        {s.turn_count} turn{s.turn_count === 1 ? '' : 's'}
                        {active ? ' · active' : ''}
                      </span>
                      <span aria-hidden="true" className="text-gray-300">
                        ·
                      </span>
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation()
                          startRename(s)
                        }}
                        aria-label="Rename session"
                        title="Rename"
                        className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-800 transition-colors"
                      >
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
                          <path d="M12 20h9" />
                          <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                        </svg>
                      </button>
                      {confirmingId === s.id ? (
                        <span className="inline-flex items-center gap-1">
                          <span className="text-gray-600">Delete?</span>
                          <button
                            type="button"
                            onClick={e => {
                              e.stopPropagation()
                              setConfirmingId(null)
                              onDelete(s.id)
                            }}
                            disabled={busyId === s.id}
                            className="font-medium text-red-600 hover:text-rose-800 disabled:opacity-60"
                          >
                            {busyId === s.id ? 'Deleting…' : 'Yes'}
                          </button>
                          <button
                            type="button"
                            onClick={e => {
                              e.stopPropagation()
                              setConfirmingId(null)
                            }}
                            className="font-medium text-gray-500 hover:text-gray-800 transition-colors"
                          >
                            No
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={e => {
                            e.stopPropagation()
                            setConfirmingId(s.id)
                          }}
                          aria-label="Delete session"
                          title="Delete"
                          className="rounded p-1 text-red-600 hover:bg-gray-100 hover:text-rose-800 transition-colors"
                        >
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
                            <path d="M3 6h18" />
                            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                            <path d="M10 11v6" />
                            <path d="M14 11v6" />
                          </svg>
                        </button>
                      )}
                    </div>

                    {/* Row 3: session start + last-updated timestamps — single line, truncates */}
                    {(fmtTime(s.created_at) || fmtTime(s.updated_at)) && (
                      <div className="mt-0.5 overflow-hidden text-ellipsis whitespace-nowrap pl-[1.375rem] text-[10px] text-gray-400">
                        {fmtTime(s.created_at) && <span>Started {fmtTime(s.created_at)}</span>}
                        {fmtTime(s.created_at) && fmtTime(s.updated_at) && (
                          <span aria-hidden="true"> · upd </span>
                        )}
                        {fmtTime(s.updated_at) &&
                          (fmtTime(s.created_at) ? (
                            <span>{fmtTime(s.updated_at)}</span>
                          ) : (
                            <span>Updated {fmtTime(s.updated_at)}</span>
                          ))}
                      </div>
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

/**
 * Thin container: owns all data loading, `api.*` CRUD, and async state, then
 * renders `<SessionSidebarView ... />`. Public signature is unchanged.
 */
export function SessionSidebar({
  activeSessionId,
  refreshToken,
  onResume,
  onNew,
  onSessionDeleted,
  onAllDeleted,
  onOpenMemory,
}: {
  activeSessionId: string | null
  refreshToken: number
  onResume: (id: string) => void
  onNew: () => void
  onSessionDeleted: (id: string) => void
  onAllDeleted: () => void
  onOpenMemory: () => void
}) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [busyId, setBusyId] = useState<string | null>(null)
  const [clearingAll, setClearingAll] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await api.listSessions()
      setSessions(Array.isArray(list) ? list : [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sessions.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  const handleRename = useCallback(
    async (id: string, name: string) => {
      setBusyId(id)
      try {
        await api.renameSession(id, name)
        await load()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to rename session.')
      } finally {
        setBusyId(null)
      }
    },
    [load],
  )

  const handleDelete = useCallback(
    async (id: string) => {
      setBusyId(id)
      try {
        await api.deleteSession(id)
        setSessions(prev => prev.filter(s => s.id !== id))
        onSessionDeleted(id)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete session.')
      } finally {
        setBusyId(null)
      }
    },
    [onSessionDeleted],
  )

  const handleClearAll = useCallback(async () => {
    setClearingAll(true)
    try {
      await api.deleteAllSessions()
      setSessions([])
      onAllDeleted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear sessions.')
    } finally {
      setClearingAll(false)
    }
  }, [onAllDeleted])

  const handleBulkDelete = useCallback(
    async (ids: string[]) => {
      if (ids.length === 0) return
      setBulkDeleting(true)
      try {
        const result = await api.bulkDeleteSessions(ids)
        // Re-fetch to get the accurate post-delete list (server may skip some).
        const remaining = await api.listSessions()
        setSessions(Array.isArray(remaining) ? remaining : [])
        // Notify parent for each id no longer present in the refreshed list.
        const remainingIds = new Set(
          (Array.isArray(remaining) ? remaining : []).map(s => s.id),
        )
        for (const id of ids) {
          if (!remainingIds.has(id)) {
            onSessionDeleted(id)
          }
        }
        void result // suppress unused-var warning
      } catch (err) {
        alert(err instanceof Error ? err.message : 'Failed to delete selected sessions.')
      } finally {
        setBulkDeleting(false)
      }
    },
    [onSessionDeleted],
  )

  return (
    <SessionSidebarView
      sessions={sessions}
      activeSessionId={activeSessionId}
      loading={loading}
      error={error}
      busyId={busyId}
      bulkDeleting={bulkDeleting}
      clearingAll={clearingAll}
      onResume={onResume}
      onNew={onNew}
      onOpenMemory={onOpenMemory}
      onRetry={() => void load()}
      onRename={(id, name) => void handleRename(id, name)}
      onDelete={id => void handleDelete(id)}
      onClearAll={() => void handleClearAll()}
      onBulkDelete={ids => void handleBulkDelete(ids)}
    />
  )
}
