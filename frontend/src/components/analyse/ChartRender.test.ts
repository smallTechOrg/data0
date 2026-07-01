/**
 * ChartRender.test.ts — logic tests for the chart theme-awareness slice (C34).
 *
 * The two pure functions under test (readThemeColors, buildThemeOption) live
 * in chartTheme.ts — a plain .ts module extracted from ChartRender.tsx so
 * Node's built-in test runner can import them directly. (ChartRender.tsx
 * itself is a visual/UI component wrapping JSX/ECharts — automated tests
 * can't verify on-screen chart appearance, and Node's
 * `--experimental-strip-types` loader cannot parse a `.tsx` file's JSX, only
 * plain TypeScript, hence the split.) ChartRender.tsx imports and re-exports
 * both functions from chartTheme.ts, so its public API is unchanged.
 *
 * These tests focus on the two pieces of real, pure logic added by this slice:
 *   1. readThemeColors() — reading CSS custom properties off an element via
 *      getComputedStyle, with light-mode fallbacks when a variable is unset.
 *   2. buildThemeOption() — mapping those colors into the ECharts option
 *      fragment merged via chart.setOption(...).
 *
 * Run with: node --experimental-strip-types --test src/components/analyse/ChartRender.test.ts
 * (see the exact command reported in the slice handoff).
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildThemeOption, readThemeColors } from './chartTheme.ts'

/** Minimal CSSStyleDeclaration stand-in exposing only getPropertyValue. */
class FakeComputedStyle {
  private vars: Record<string, string>
  constructor(vars: Record<string, string>) {
    this.vars = vars
  }
  getPropertyValue(name: string): string {
    return this.vars[name] ?? ''
  }
}

/** Minimal HTMLElement stand-in — readThemeColors only needs to pass it through to getComputedStyle. */
class FakeElement {}

/** Installs a stubbed global getComputedStyle for the duration of `fn`, then restores it. */
function withComputedStyle<T>(vars: Record<string, string>, fn: () => T): T {
  const original = (globalThis as { getComputedStyle?: typeof getComputedStyle }).getComputedStyle
  ;(globalThis as { getComputedStyle: (el: Element) => CSSStyleDeclaration }).getComputedStyle = () =>
    new FakeComputedStyle(vars) as unknown as CSSStyleDeclaration
  try {
    return fn()
  } finally {
    if (original) {
      ;(globalThis as { getComputedStyle: typeof getComputedStyle }).getComputedStyle = original
    }
  }
}

test('readThemeColors falls back to light-mode defaults when no CSS variables are set', () => {
  const colors = withComputedStyle({}, () => readThemeColors(new FakeElement() as unknown as HTMLElement))
  assert.equal(colors.surface, '#ffffff')
  assert.equal(colors.text, '#111827')
  assert.equal(colors.textSecondary, '#374151')
  assert.equal(colors.textMuted, '#6b7280')
  assert.equal(colors.border, '#e5e7eb')
})

test('readThemeColors reads dark-theme values when the CSS variables resolve to them', () => {
  const darkVars = {
    '--surface': '#111827',
    '--text': '#e5e7eb',
    '--text-secondary': '#9ca3af',
    '--text-muted': '#6b7280',
    '--border': '#2a3549',
  }
  const colors = withComputedStyle(darkVars, () => readThemeColors(new FakeElement() as unknown as HTMLElement))
  assert.equal(colors.surface, '#111827')
  assert.equal(colors.text, '#e5e7eb')
  assert.equal(colors.textSecondary, '#9ca3af')
  assert.equal(colors.textMuted, '#6b7280')
  assert.equal(colors.border, '#2a3549')
})

test('readThemeColors treats a whitespace-only custom property as unset and falls back', () => {
  const colors = withComputedStyle(
    { '--surface': '   ', '--text': '\n' },
    () => readThemeColors(new FakeElement() as unknown as HTMLElement),
  )
  assert.equal(colors.surface, '#ffffff')
  assert.equal(colors.text, '#111827')
})

test('buildThemeOption maps theme colors onto background/text/legend/axis/tooltip', () => {
  const option = buildThemeOption({
    surface: '#111827',
    text: '#e5e7eb',
    textSecondary: '#9ca3af',
    textMuted: '#6b7280',
    border: '#2a3549',
  }) as Record<string, unknown>

  assert.equal(option.backgroundColor, '#111827')
  assert.deepEqual(option.textStyle, { color: '#e5e7eb' })

  const legend = option.legend as { textStyle: { color: string } }
  assert.equal(legend.textStyle.color, '#9ca3af')

  const tooltip = option.tooltip as { backgroundColor: string; borderColor: string; textStyle: { color: string } }
  assert.equal(tooltip.backgroundColor, '#111827')
  assert.equal(tooltip.borderColor, '#2a3549')
  assert.equal(tooltip.textStyle.color, '#e5e7eb')

  const xAxis = option.xAxis as {
    axisLine: { lineStyle: { color: string } }
    axisLabel: { color: string }
    axisTick: { lineStyle: { color: string } }
    splitLine: { lineStyle: { color: string } }
  }
  assert.equal(xAxis.axisLine.lineStyle.color, '#2a3549')
  assert.equal(xAxis.axisLabel.color, '#9ca3af')
  assert.equal(xAxis.axisTick.lineStyle.color, '#2a3549')
  assert.equal(xAxis.splitLine.lineStyle.color, '#2a3549')

  const yAxis = option.yAxis as { axisLabel: { color: string } }
  assert.equal(yAxis.axisLabel.color, '#9ca3af')
})

test('buildThemeOption never crashes on an empty-string color (defensive — always a string)', () => {
  const option = buildThemeOption({
    surface: '',
    text: '',
    textSecondary: '',
    textMuted: '',
    border: '',
  }) as Record<string, unknown>
  assert.equal(option.backgroundColor, '')
})
