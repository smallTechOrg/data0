/**
 * chartTheme.ts — theme-derived colors ECharts needs at draw time (C34 — theming).
 *
 * Extracted from ChartRender.tsx (a design-synced component, see
 * `.design-sync/config.json` -> `componentSrcMap`) into a plain `.ts` module so
 * these two pure functions have real, runnable automated coverage: Node's
 * built-in `--experimental-strip-types` test runner can execute a `.ts` file
 * directly, but throws `ERR_UNKNOWN_FILE_EXTENSION` on a `.tsx` import (JSX
 * syntax needs a JSX-aware transform Node's stripper doesn't provide).
 * ChartRender.tsx re-imports and re-exports both functions from here, so its
 * public API (and every other file's imports of it) is unchanged.
 *
 * `echarts.init(el)` renders into a plain `<canvas>`, which has no CSS
 * cascade, so the chart's own background, axis lines, tick labels, and
 * legend text must be set programmatically from the active theme rather than
 * via Tailwind classes.
 */

/**
 * Plain values (light-mode defaults, matching the app's untheming look) used
 * as a fallback whenever a CSS custom property is missing/empty — e.g. before
 * slice-7a's `globals.css` variables exist, or in a test environment with no
 * stylesheet at all — so a chart never breaks even if the theme CSS hasn't
 * loaded.
 */
const THEME_COLOR_FALLBACKS = {
  surface: '#ffffff',
  text: '#111827',
  textSecondary: '#374151',
  textMuted: '#6b7280',
  border: '#e5e7eb',
} as const

export type ThemeColors = {
  surface: string
  text: string
  textSecondary: string
  textMuted: string
  border: string
}

/** An ECharts option object — opaque beyond the required `series` key. */
export type EChartsOption = Record<string, unknown>

/**
 * Read the active theme's CSS custom properties off `document.documentElement`
 * (the element slice-7a's `data-theme`/`data-accent`/`data-density` attributes
 * live on, and where `globals.css` defines the `--surface`/`--text`/etc.
 * variables). Falls back to the light-mode default for any variable that is
 * unset or empty, so this never throws and never renders a blank chart.
 *
 * Exported (not just used internally) so it can be unit-tested directly
 * against a stubbed `getComputedStyle`.
 */
export function readThemeColors(root: HTMLElement = document.documentElement): ThemeColors {
  const style = getComputedStyle(root)
  const read = (varName: string, fallback: string): string => {
    const value = style.getPropertyValue(varName).trim()
    return value === '' ? fallback : value
  }
  return {
    surface: read('--surface', THEME_COLOR_FALLBACKS.surface),
    text: read('--text', THEME_COLOR_FALLBACKS.text),
    textSecondary: read('--text-secondary', THEME_COLOR_FALLBACKS.textSecondary),
    textMuted: read('--text-muted', THEME_COLOR_FALLBACKS.textMuted),
    border: read('--border', THEME_COLOR_FALLBACKS.border),
  }
}

/**
 * Build the ECharts option fragment that re-themes background/axis/legend/text
 * colors. Merged into the chart's own `option` via `chart.setOption(...)` —
 * ECharts merges `setOption` calls shallowly per top-level key, so this does
 * not clobber the chart's data/series, only the visual chrome.
 *
 * Exported for unit testing independent of a live ECharts/DOM instance.
 */
export function buildThemeOption(colors: ThemeColors): EChartsOption {
  const axisLineStyle = { lineStyle: { color: colors.border } }
  const axisLabelStyle = { color: colors.textSecondary }
  const axisTickStyle = { lineStyle: { color: colors.border } }
  const splitLineStyle = { lineStyle: { color: colors.border } }

  return {
    backgroundColor: colors.surface,
    textStyle: { color: colors.text },
    title: { textStyle: { color: colors.text }, subtextStyle: { color: colors.textMuted } },
    legend: { textStyle: { color: colors.textSecondary } },
    tooltip: {
      backgroundColor: colors.surface,
      borderColor: colors.border,
      textStyle: { color: colors.text },
    },
    xAxis: {
      axisLine: axisLineStyle,
      axisLabel: axisLabelStyle,
      axisTick: axisTickStyle,
      splitLine: splitLineStyle,
    },
    yAxis: {
      axisLine: axisLineStyle,
      axisLabel: axisLabelStyle,
      axisTick: axisTickStyle,
      splitLine: splitLineStyle,
    },
  }
}
