'use client'

import { useCallback, useEffect, useState } from 'react'
import { StubBanner } from '@/components/StubBanner'
import { ThemeControls } from '@/components/ThemeControls'
import { AnalyseTab } from '@/components/analyse/AnalyseTab'
import { DatabaseTab } from '@/components/database/DatabaseTab'
import { MemoryModal } from '@/components/analyse/MemoryModal'
import { api } from '@/lib/api'
import { DEFAULT_ACCENT, DEFAULT_DENSITY, DEFAULT_THEME, initTheme, type ThemePrefs } from '@/lib/theme'

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
  // Theme/accent/density — client-only visual preference, never sent to the
  // backend (see spec/capabilities/theming.md). Seeded with the untheming
  // defaults so server-rendered markup matches the client's first paint;
  // the real persisted choice is read and applied in the mount effect below.
  const [themePrefs, setThemePrefs] = useState<ThemePrefs>({
    theme: DEFAULT_THEME,
    accent: DEFAULT_ACCENT,
    density: DEFAULT_DENSITY,
  })

  // Apply the persisted theme/accent/density to <html> as early as possible
  // on mount, before the rest of the tree's colors would otherwise paint with
  // the light-mode default. A brief flash on hard reload is an accepted
  // limitation (see theming.md) since this can't run before hydration.
  useEffect(() => {
    setThemePrefs(initTheme())
  }, [])

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
    <div className="min-h-screen bg-gray-50">
      {/* Stub-mode banner — shown only when the backend runs without an LLM key. */}
      <StubBanner provider={provider} />

      {/* Header — solid indigo bar: title (left), pill tabs (inline), and the
          Live badge + Project notes button (right). */}
      <header className="bg-indigo-900 text-white shadow-lg">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-x-8 gap-y-4 px-6 py-5">
          {/* Left: title + thin tagline + inline pill tabs */}
          <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
            <div>
              <div className="flex items-center gap-3">
                <span className="text-3xl">📊</span>
                <h1 className="text-2xl font-bold leading-tight tracking-tighter">
                  Data Analysis Agent
                </h1>
              </div>
              <p className="mt-1 text-sm font-normal text-indigo-200">
                Ask questions, get explainable answers.
              </p>
            </div>

            {/* Tab switcher (local UI state — allowed in Phase 1) */}
            <div role="tablist" aria-label="Views" className="flex gap-3">
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

          {/* Right: theme/accent/density controls + live badge + Project notes */}
          <div className="flex items-center gap-4">
            <ThemeControls prefs={themePrefs} onChange={setThemePrefs} />
            {isLive && (
              <span
                className="inline-flex items-center gap-2 rounded-full bg-white/15 px-3.5 py-2 text-sm font-medium text-white backdrop-blur-sm transition-colors hover:bg-white/20"
                title={`Live — provider: ${provider}${model ? `, model: ${model}` : ''}`}
              >
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-green-400 animate-pulse" />
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
          ? 'bg-white tab-active-label shadow-md'
          : 'text-white hover:bg-white/20'
      }`}
    >
      {label}
    </button>
  )
}

