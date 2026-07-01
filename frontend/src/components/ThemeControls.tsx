'use client'

import { useCallback } from 'react'
import {
  ACCENTS,
  DENSITIES,
  THEMES,
  setPref,
  type Accent,
  type Density,
  type Theme,
  type ThemePrefs,
} from '@/lib/theme'

const ACCENT_SWATCH_CLASS: Record<Accent, string> = {
  blue: 'bg-blue-500',
  purple: 'bg-purple-500',
  green: 'bg-green-500',
  orange: 'bg-orange-500',
}

const ACCENT_LABEL: Record<Accent, string> = {
  blue: 'Blue',
  purple: 'Purple',
  green: 'Green',
  orange: 'Orange',
}

const DENSITY_LABEL: Record<Density, string> = {
  compact: 'Compact',
  comfortable: 'Comfortable',
  spacious: 'Spacious',
}

/**
 * <ThemeControls prefs onChange /> — the three visual-preference controls
 * (theme toggle, accent picker, density picker) rendered in AppShell's header
 * right-hand control cluster, next to the "Live" badge / "Project notes"
 * button. Pure client-side, zero network/LLM calls (spec/capabilities/theming.md).
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

  const handleAccentPick = useCallback(
    (accent: Accent) => {
      if (accent === prefs.accent) return
      onChange(setPref('accent', accent, prefs))
    },
    [prefs, onChange],
  )

  const handleDensityPick = useCallback(
    (density: Density) => {
      if (density === prefs.density) return
      onChange(setPref('density', density, prefs))
    },
    [prefs, onChange],
  )

  const isDark = prefs.theme === 'dark'

  return (
    <div className="flex items-center gap-3">
      {/* Theme toggle — sun/moon icon button. */}
      <button
        type="button"
        onClick={handleThemeToggle}
        aria-pressed={isDark}
        title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/15 text-base text-white transition-colors hover:bg-white/25 backdrop-blur-sm"
      >
        <span aria-hidden="true">{isDark ? '\u{1F319}' : '\u{2600}\u{FE0F}'}</span>
        <span className="sr-only">{isDark ? 'Dark mode active' : 'Light mode active'}</span>
      </button>

      {/* Accent picker — 4 color swatches. */}
      <div
        role="radiogroup"
        aria-label="Accent color"
        className="flex items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1.5 backdrop-blur-sm"
      >
        {ACCENTS.map(accent => (
          <button
            key={accent}
            type="button"
            role="radio"
            aria-checked={prefs.accent === accent}
            title={ACCENT_LABEL[accent]}
            onClick={() => handleAccentPick(accent)}
            className={`h-5 w-5 rounded-full ${ACCENT_SWATCH_CLASS[accent]} transition-transform ${
              prefs.accent === accent
                ? 'ring-2 ring-white ring-offset-1 ring-offset-indigo-900 scale-110'
                : 'opacity-70 hover:opacity-100'
            }`}
          >
            <span className="sr-only">{ACCENT_LABEL[accent]}</span>
          </button>
        ))}
      </div>

      {/* Density picker — 3-option segmented control. */}
      <div
        role="radiogroup"
        aria-label="Density"
        className="flex items-center gap-0.5 rounded-lg bg-white/15 p-0.5 text-xs font-medium text-white backdrop-blur-sm"
      >
        {DENSITIES.map(density => (
          <button
            key={density}
            type="button"
            role="radio"
            aria-checked={prefs.density === density}
            title={DENSITY_LABEL[density]}
            onClick={() => handleDensityPick(density)}
            className={`rounded-md px-2 py-1 transition-colors ${
              prefs.density === density ? 'bg-white text-indigo-600 shadow' : 'hover:bg-white/20'
            }`}
          >
            {DENSITY_LABEL[density][0]}
            <span className="sr-only">{DENSITY_LABEL[density]}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export const THEME_OPTIONS = THEMES
