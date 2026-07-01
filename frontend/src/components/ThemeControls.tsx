'use client'

import { useCallback } from 'react'
import { THEMES, setPref, type Theme, type ThemePrefs } from '@/lib/theme'

/**
 * <ThemeControls prefs onChange /> — the light/dark toggle rendered in
 * AppShell's header right-hand control cluster, next to the "Live" badge /
 * "Project notes" button. Pure client-side, zero network/LLM calls
 * (spec/capabilities/theming.md).
 *
 * Accent and density are fixed product decisions (indigo accent, compact
 * density) rather than user preferences, so there is no picker for either —
 * see `readStoredPrefs` in `lib/theme.ts`.
 *
 * Fully controlled: the caller (AppShell) owns the current `ThemePrefs` state
 * and re-renders this component when it changes; this component only reads
 * `prefs` and calls `onChange` with the next full preference set (which also
 * persists to localStorage and applies the DOM attributes via `setPref`).
 */
export function ThemeControls({
  prefs,
  onChange,
}: {
  prefs: ThemePrefs
  onChange: (next: ThemePrefs) => void
}) {
  const handleThemeToggle = useCallback(() => {
    const next: Theme = prefs.theme === 'light' ? 'dark' : 'light'
    onChange(setPref('theme', next, prefs))
  }, [prefs, onChange])

  const isDark = prefs.theme === 'dark'

  return (
    <button
      type="button"
      onClick={handleThemeToggle}
      aria-pressed={isDark}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/15 text-base text-white transition-colors hover:bg-white/25 backdrop-blur-sm"
    >
      <span aria-hidden="true">{isDark ? '\u{1F319}' : '\u{2600}\u{FE0F}'}</span>
      <span className="sr-only">{isDark ? 'Dark mode active' : 'Light mode active'}</span>
    </button>
  )
}

export const THEME_OPTIONS = THEMES
