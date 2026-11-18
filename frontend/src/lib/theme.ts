/**
 * theme.ts — client-only theme/accent/density preference store.
 *
 * Owns reading/writing the three `localStorage` keys and applying the
 * `data-theme` / `data-accent` / `data-density` attributes to
 * `document.documentElement`. Pure client-side visual preference: no network
 * call, no backend persistence (see spec/capabilities/theming.md).
 *
 * Consumed by `ThemeControls.tsx` (the controls) and `ChartRender.tsx`'s
 * theme-change listener (reads the same attribute contract + CSS variables).
 */

export type Theme = 'light' | 'dark'
export type Accent = 'blue' | 'purple' | 'green' | 'orange'
export type Density = 'compact' | 'comfortable' | 'spacious'

export const THEMES: readonly Theme[] = ['light', 'dark']
export const ACCENTS: readonly Accent[] = ['blue', 'purple', 'green', 'orange']
export const DENSITIES: readonly Density[] = ['compact', 'comfortable', 'spacious']

export const DEFAULT_THEME: Theme = 'light'
export const DEFAULT_ACCENT: Accent = 'blue'
export const DEFAULT_DENSITY: Density = 'compact'

const STORAGE_KEYS = {
  theme: 'daa.theme',
  accent: 'daa.accent',
  density: 'daa.density',
} as const

export interface ThemePrefs {
  theme: Theme
  accent: Accent
  density: Density
}

function isTheme(value: string | null): value is Theme {
  return value === 'light' || value === 'dark'
}

/** `window.localStorage`, or undefined when absent. Merely reading it can throw when storage is denied. */
function browserStorage(): Storage | undefined {
  try {
    return typeof window !== 'undefined' ? window.localStorage : undefined
  } catch {
    return undefined
  }
}

/**
 * Reads persisted preferences from `localStorage`, falling back to defaults
 * for any key that is absent or holds an unrecognised value. Safe to call in
 * non-browser contexts (returns defaults) — guards every `localStorage`
 * access so a SSR/build-time call never throws.
 *
 * Accent and density are pinned to their defaults regardless of any stored
 * value — there is no picker for either (indigo accent + compact density are
 * fixed product decisions, not user preferences) — but the `data-accent`/
 * `data-density` attribute contract stays in place for `ChartRender.tsx` and
 * the CSS remap, which still key off them.
 */
export function readStoredPrefs(storage?: Storage): ThemePrefs {
  const store = storage ?? browserStorage()

  if (!store) {
    return { theme: DEFAULT_THEME, accent: DEFAULT_ACCENT, density: DEFAULT_DENSITY }
  }

  let rawTheme: string | null = null
  try {
    rawTheme = store.getItem(STORAGE_KEYS.theme)
  } catch {
    // localStorage can throw (e.g. disabled/private-mode quota) — fall back
    // to defaults rather than let a preference read crash the app.
  }

  return {
    theme: isTheme(rawTheme) ? rawTheme : DEFAULT_THEME,
    accent: DEFAULT_ACCENT,
    density: DEFAULT_DENSITY,
  }
}

/** Persists one preference key to `localStorage`. Swallows storage errors. */
export function storePref<K extends keyof ThemePrefs>(
  key: K,
  value: ThemePrefs[K],
  storage?: Storage,
): void {
  const store = storage ?? browserStorage()
  if (!store) return
  try {
    store.setItem(STORAGE_KEYS[key], value)
  } catch {
    // Ignore — a failed write just means the choice won't survive reload.
  }
}

/**
 * Applies the full preference set to `document.documentElement` as
 * `data-theme` / `data-accent` / `data-density` attributes. This is the sole
 * mechanism the CSS-variable remap in `globals.css` keys off of. Safe to call
 * in a non-browser context (no-op).
 */
export function applyPrefsToDocument(prefs: ThemePrefs, root?: HTMLElement): void {
  const el = root ?? (typeof document !== 'undefined' ? document.documentElement : undefined)
  if (!el) return
  el.setAttribute('data-theme', prefs.theme)
  el.setAttribute('data-accent', prefs.accent)
  el.setAttribute('data-density', prefs.density)
}

/**
 * Reads persisted prefs and applies them to the document in one call — the
 * single entry point used on mount (before first paint of themed content).
 */
export function initTheme(storage?: Storage, root?: HTMLElement): ThemePrefs {
  const prefs = readStoredPrefs(storage)
  applyPrefsToDocument(prefs, root)
  return prefs
}

/**
 * Sets one preference: persists it to `localStorage` and applies it to the
 * document immediately. Used by `ThemeControls.tsx` on every click.
 */
export function setPref<K extends keyof ThemePrefs>(
  key: K,
  value: ThemePrefs[K],
  current: ThemePrefs,
  storage?: Storage,
  root?: HTMLElement,
): ThemePrefs {
  storePref(key, value, storage)
  const next: ThemePrefs = { ...current, [key]: value }
  applyPrefsToDocument(next, root)
  return next
}
