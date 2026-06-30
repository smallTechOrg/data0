'use client'

import { useCallback, useEffect, useState } from 'react'
import { StubBanner } from '@/components/StubBanner'
import { AnalyseTab } from '@/components/analyse/AnalyseTab'
import { DatabaseTab } from '@/components/database/DatabaseTab'
import { MemoryModal } from '@/components/analyse/MemoryModal'
import { api } from '@/lib/api'

type Tab = 'analyse' | 'database'

/**
 * AppShell — the shell for the Data Analysis Agent.
 *
 * A single blue header bar holds the app name + thin tagline, the Analyse
 * (default) / Database tabs as inline pill buttons (active = filled white,
 * inactive = translucent), and the Live badge + "Project notes" button on the
 * right; the conditional yellow stub-mode banner sits above it. Below the bar is
 * the responsive panel layout for the active tab.
 *
 * Health is fetched once on mount: its `provider` drives the stub banner (shown
 * only in stub mode) and a subtle "live" indicator when a real provider is set.
 * The Database tab and the Project-notes button remain labelled stubs in Phase 2.
 */
export function AppShell() {
  const [tab, setTab] = useState<Tab>('analyse')
  // undefined = still loading health; string = resolved provider.
  const [provider, setProvider] = useState<string | undefined>(undefined)
  // The model the provider will actually call (drives the header badge).
  const [model, setModel] = useState<string | undefined>(undefined)
  // Global-memory ("Project notes") modal — REAL in Phase 3.
  const [memoryOpen, setMemoryOpen] = useState(false)

  // Fetch /health (provider + active model). Called on mount and again after a
  // settings save, so the header badge reflects a model change without a reload.
  const refreshHealth = useCallback(() => {
    api
      .health()
      .then(h => {
        setProvider(h.provider)
        setModel(h.model || undefined)
      })
      .catch(() => {
        // Health failed (e.g. server not reachable yet) — leave provider
        // unresolved so we neither flash a stub banner nor claim "live".
        setProvider(undefined)
      })
  }, [])

  useEffect(() => {
    refreshHealth()
  }, [refreshHealth])

  const isLive = provider === 'gemini' || provider === 'openrouter' || provider === 'anthropic'

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Stub-mode banner — shown only when the backend runs without an LLM key. */}
      <StubBanner provider={provider} />

      {/* Header — gradient bar: title (left), pill tabs (inline), and the
          Live badge + Project notes button (right). */}
      <header className="bg-gradient-to-r from-indigo-600 to-blue-600 text-white shadow-md">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-4">
          {/* Left: title + thin tagline + inline pill tabs */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-2xl">📊</span>
                <h1 className="text-xl font-bold leading-tight tracking-tight">
                  Data Analysis Agent
                </h1>
              </div>
              <p className="text-sm text-indigo-100">
                Ask questions in plain English, get explainable answers.
              </p>
            </div>

            {/* Tab switcher (local UI state — allowed in Phase 1) */}
            <div role="tablist" aria-label="Views" className="flex gap-2">
              <TabButton
                id="tab-analyse"
                label="Analyse"
                active={tab === 'analyse'}
                onClick={() => setTab('analyse')}
              />
              <TabButton
                id="tab-database"
                label="Database"
                active={tab === 'database'}
                onClick={() => setTab('database')}
              />
            </div>
          </div>

          {/* Right: live badge + Project notes */}
          <div className="flex items-center gap-3">
            {isLive && (
              <span
                className="inline-flex items-center gap-2 rounded-full bg-white/20 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-sm"
                title={`Live — provider: ${provider}${model ? `, model: ${model}` : ''}`}
              >
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-emerald-300 animate-pulse" />
                Live · {model ?? provider}
              </span>
            )}
            <button
              type="button"
              onClick={() => setMemoryOpen(true)}
              title="Edit the agent's global project notes (memory)"
              className="rounded-lg bg-white/15 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/25 backdrop-blur-sm"
            >
              📝 Project notes
            </button>
          </div>
        </div>
      </header>

      {/* Active tab */}
      <main className="mx-auto max-w-[1600px] px-6 py-8">
        {/* Analyse stays MOUNTED across tab switches (only hidden) so the active
            session + conversation survive a trip to the Database tab — clicking
            Database must not reset it. Database re-mounts on show for its fetch. */}
        <div
          role="tabpanel"
          id="panel-analyse"
          aria-labelledby="tab-analyse"
          hidden={tab !== 'analyse'}
        >
          <AnalyseTab
            provider={provider}
            model={model}
            active={tab === 'analyse'}
            onOpenMemory={() => setMemoryOpen(true)}
            onSettingsSaved={refreshHealth}
          />
        </div>
        <div
          role="tabpanel"
          id="panel-database"
          aria-labelledby="tab-database"
          hidden={tab !== 'database'}
        >
          {tab === 'database' && <DatabaseTab />}
        </div>
      </main>

      {/* Global-memory / Project notes modal (reachable from header + sidebar). */}
      <MemoryModal open={memoryOpen} onClose={() => setMemoryOpen(false)} />
    </div>
  )
}

function TabButton({
  id,
  label,
  active,
  onClick,
}: {
  id: string
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      id={id}
      role="tab"
      aria-selected={active}
      aria-controls={`panel-${label.toLowerCase()}`}
      onClick={onClick}
      className={`rounded-lg px-4 py-2 text-sm font-medium transition-all ${
        active
          ? 'bg-white text-indigo-600 shadow-md'
          : 'text-white hover:bg-white/20'
      }`}
    >
      {label}
    </button>
  )
}
