'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { SessionSidebar } from '@/components/analyse/SessionSidebar'
import { TokenWidget } from '@/components/analyse/TokenWidget'
import {
  ConversationCard,
  type ConversationHandle,
} from '@/components/analyse/ConversationCard'
import { SettingsPanel } from '@/components/analyse/SettingsPanel'

/** Token counts from the most recent completed ask (drives the TokenWidget). */
export interface LastQueryTokens {
  input: number
  output: number
}

/**
 * Analyse tab — the real Phase-3 surface.
 *
 * Owns the shared state the cards coordinate on:
 *  - `sessionId`          : the active conversation session. New is created
 *    server-side on the next /ask with no session_id; the answer's session_id is
 *    adopted here. Resuming a session loads its turns into the conversation card.
 *  - `datasetsVersion`    : a bump token that keeps the Token widget's dataset
 *    aggregate (Datasets/Rows) fresh — data itself is managed on the Database
 *    tab (Upload + Tables live there now), but this tab still needs to know
 *    when the universe changes.
 *  - `sessionsVersion`    : a bump token telling the sidebar to re-fetch (after
 *    each ask, so turn counts / ordering update).
 *  - `lastTokens`         : in/out tokens from the latest answer (Token widget).
 *
 * The global-memory ("Project notes") modal is hoisted to AppShell so the header
 * button and the sidebar button open the same modal; `onOpenMemory` opens it.
 *
 * Layout: a left sidebar (sessions + token usage) and a main column (the
 * conversation). Stacks on narrow viewports. Data management (upload, tables,
 * schema) lives on the Database tab, which is now the app's default/landing tab.
 */
export function AnalyseTab({
  provider,
  model,
  active = true,
  onOpenMemory,
  onSettingsSaved,
}: {
  provider?: string
  /** Active model id (passed to the conversation for session export). */
  model?: string
  /** Whether the Analyse tab is the visible one (it stays mounted when hidden). */
  active?: boolean
  onOpenMemory: () => void
  /** Notify the shell after a settings save so the header re-fetches /health. */
  onSettingsSaved?: () => void
}) {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [datasetsVersion, setDatasetsVersion] = useState(0)
  const [sessionsVersion, setSessionsVersion] = useState(0)
  const [lastTokens, setLastTokens] = useState<LastQueryTokens | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsVersion, setSettingsVersion] = useState(0)

  const conversationRef = useRef<ConversationHandle>(null)

  const refreshDatasets = useCallback(() => setDatasetsVersion(v => v + 1), [])
  const refreshSessions = useCallback(() => setSessionsVersion(v => v + 1), [])

  // The tab stays mounted when hidden, so its state (active session,
  // conversation) survives a switch to the Database tab. Database is the app's
  // landing tab now, so the user's FIRST visit here typically happens after
  // they've already uploaded data there — every activation (including the
  // first) must refresh so the Token widget's dataset aggregate isn't stale.
  // This never double-fetches at load time: `active` is false until the user
  // actually switches to this tab (Database is the default).
  useEffect(() => {
    if (!active) return
    refreshDatasets()
    refreshSessions()
  }, [active, refreshDatasets, refreshSessions])

  // --- Session lifecycle ----------------------------------------------------

  // +New: clear the active conversation; the next ask starts a fresh session.
  const handleNewSession = useCallback(() => {
    setSessionId(null)
    conversationRef.current?.reset()
  }, [])

  // Resume: load the session detail and hydrate the conversation thread.
  const handleResume = useCallback(async (id: string) => {
    try {
      const detail = await api.getSession(id)
      setSessionId(detail.id)
      conversationRef.current?.hydrate(detail)
    } catch {
      // A failed resume leaves the current thread untouched; the sidebar will
      // surface the error on its own next refresh. Reset to a clean state so the
      // user isn't stuck on a half-loaded session.
      setSessionId(id)
      conversationRef.current?.reset()
    }
  }, [])

  // The conversation card adopts the server-assigned session id after an ask.
  const handleSessionStarted = useCallback(
    (id: string) => {
      setSessionId(prev => (prev === id ? prev : id))
      // New/continued session → refresh the sidebar so it appears / updates.
      refreshSessions()
    },
    [refreshSessions],
  )

  const handleSessionDeleted = useCallback(
    (id: string) => {
      if (sessionId === id) {
        setSessionId(null)
        conversationRef.current?.reset()
      }
    },
    [sessionId],
  )

  const handleAllSessionsDeleted = useCallback(() => {
    setSessionId(null)
    conversationRef.current?.reset()
  }, [])

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[22rem_1fr]">
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={() => {
          setSettingsVersion(v => v + 1)
          onSettingsSaved?.()
        }}
      />

      {/* Sidebar — Settings sits at the bottom-left, below sessions + usage.
          Sticky on large screens so it stays in view while the main column
          scrolls; grows with its content (no nested scroll region) — if it's
          ever taller than the viewport, the page scrolls instead. */}
      <aside className="flex flex-col gap-4 lg:sticky lg:top-20 lg:self-start">
        <SessionSidebar
          activeSessionId={sessionId}
          refreshToken={sessionsVersion}
          onResume={id => void handleResume(id)}
          onNew={handleNewSession}
          onSessionDeleted={handleSessionDeleted}
          onAllDeleted={handleAllSessionsDeleted}
          onOpenMemory={onOpenMemory}
        />
        <TokenWidget
          provider={provider}
          lastTokens={lastTokens}
          settingsVersion={settingsVersion}
          datasetsVersion={datasetsVersion}
        />
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="flex w-full items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 shadow-sm hover:bg-gray-50"
          aria-label="Open settings"
        >
          <span aria-hidden="true">⚙</span> Settings
        </button>
      </aside>

      {/* Main column — the conversation. Data management (upload, tables,
          schema) lives on the Database tab. */}
      <ConversationCard
        handleRef={conversationRef}
        sessionId={sessionId}
        model={model}
        onSessionStarted={handleSessionStarted}
        onAnswered={tokens => {
          setLastTokens(tokens)
          refreshDatasets()
          refreshSessions()
        }}
      />
    </div>
  )
}

