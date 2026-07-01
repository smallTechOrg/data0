/**
 * theme.test.ts — logic tests for the theme/accent/density preference store.
 *
 * This is a visual/UI feature — automated tests cannot verify appearance —
 * so these tests focus on the one piece of real logic in the slice: reading
 * defaults, persisting choices, and applying the DOM attribute contract that
 * globals.css and ChartRender.tsx's theme-listener key off of.
 *
 * Run with: node --experimental-strip-types --test src/lib/theme.test.ts
 * (see the exact command reported in the slice handoff).
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  DEFAULT_ACCENT,
  DEFAULT_DENSITY,
  DEFAULT_THEME,
  applyPrefsToDocument,
  initTheme,
  readStoredPrefs,
  setPref,
  storePref,
} from './theme.ts'

/** Minimal in-memory Storage stand-in (no DOM/jsdom dependency needed). */
class MemoryStorage implements Storage {
  private map = new Map<string, string>()
  get length() {
    return this.map.size
  }
  clear(): void {
    this.map.clear()
  }
  getItem(key: string): string | null {
    return this.map.has(key) ? this.map.get(key)! : null
  }
  key(index: number): string | null {
    return Array.from(this.map.keys())[index] ?? null
  }
  removeItem(key: string): void {
    this.map.delete(key)
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value)
  }
}

/** Minimal HTMLElement stand-in exposing only setAttribute/getAttribute. */
class FakeElement {
  private attrs = new Map<string, string>()
  setAttribute(name: string, value: string): void {
    this.attrs.set(name, value)
  }
  getAttribute(name: string): string | null {
    return this.attrs.has(name) ? this.attrs.get(name)! : null
  }
}

test('readStoredPrefs returns light/blue/comfortable defaults when storage is empty', () => {
  const storage = new MemoryStorage()
  const prefs = readStoredPrefs(storage)
  assert.equal(prefs.theme, DEFAULT_THEME)
  assert.equal(prefs.accent, DEFAULT_ACCENT)
  assert.equal(prefs.density, DEFAULT_DENSITY)
})

test('readStoredPrefs returns defaults when storage is undefined (non-browser context)', () => {
  const prefs = readStoredPrefs(undefined)
  assert.deepEqual(prefs, { theme: 'light', accent: 'blue', density: 'comfortable' })
})

test('readStoredPrefs round-trips a persisted valid choice', () => {
  const storage = new MemoryStorage()
  storage.setItem('daa.theme', 'dark')
  storage.setItem('daa.accent', 'purple')
  storage.setItem('daa.density', 'spacious')
  const prefs = readStoredPrefs(storage)
  assert.deepEqual(prefs, { theme: 'dark', accent: 'purple', density: 'spacious' })
})

test('readStoredPrefs falls back to defaults for unrecognised/garbage values', () => {
  const storage = new MemoryStorage()
  storage.setItem('daa.theme', 'not-a-theme')
  storage.setItem('daa.accent', 'chartreuse')
  storage.setItem('daa.density', 'ultra-wide')
  const prefs = readStoredPrefs(storage)
  assert.deepEqual(prefs, { theme: 'light', accent: 'blue', density: 'comfortable' })
})

test('storePref persists under the documented daa.* keys', () => {
  const storage = new MemoryStorage()
  storePref('theme', 'dark', storage)
  storePref('accent', 'green', storage)
  storePref('density', 'compact', storage)
  assert.equal(storage.getItem('daa.theme'), 'dark')
  assert.equal(storage.getItem('daa.accent'), 'green')
  assert.equal(storage.getItem('daa.density'), 'compact')
})

test('applyPrefsToDocument sets data-theme/data-accent/data-density attributes', () => {
  const el = new FakeElement()
  applyPrefsToDocument(
    { theme: 'dark', accent: 'orange', density: 'spacious' },
    el as unknown as HTMLElement,
  )
  assert.equal(el.getAttribute('data-theme'), 'dark')
  assert.equal(el.getAttribute('data-accent'), 'orange')
  assert.equal(el.getAttribute('data-density'), 'spacious')
})

test('initTheme reads persisted prefs and applies them to the document in one call', () => {
  const storage = new MemoryStorage()
  storage.setItem('daa.theme', 'dark')
  storage.setItem('daa.accent', 'purple')
  storage.setItem('daa.density', 'compact')
  const el = new FakeElement()

  const returned = initTheme(storage, el as unknown as HTMLElement)

  assert.deepEqual(returned, { theme: 'dark', accent: 'purple', density: 'compact' })
  assert.equal(el.getAttribute('data-theme'), 'dark')
  assert.equal(el.getAttribute('data-accent'), 'purple')
  assert.equal(el.getAttribute('data-density'), 'compact')
})

test('initTheme applies the light/blue/comfortable defaults on first-ever load', () => {
  const storage = new MemoryStorage()
  const el = new FakeElement()

  initTheme(storage, el as unknown as HTMLElement)

  assert.equal(el.getAttribute('data-theme'), 'light')
  assert.equal(el.getAttribute('data-accent'), 'blue')
  assert.equal(el.getAttribute('data-density'), 'comfortable')
})

test('setPref persists the new value, applies it to the DOM, and returns the merged prefs', () => {
  const storage = new MemoryStorage()
  const el = new FakeElement()
  const current = { theme: 'light' as const, accent: 'blue' as const, density: 'comfortable' as const }

  const next = setPref('theme', 'dark', current, storage, el as unknown as HTMLElement)

  assert.deepEqual(next, { theme: 'dark', accent: 'blue', density: 'comfortable' })
  assert.equal(storage.getItem('daa.theme'), 'dark')
  assert.equal(el.getAttribute('data-theme'), 'dark')
  // Untouched keys are preserved and re-applied.
  assert.equal(el.getAttribute('data-accent'), 'blue')
  assert.equal(el.getAttribute('data-density'), 'comfortable')
})

test('setPref only changes the targeted key, leaving the others as-is', () => {
  const storage = new MemoryStorage()
  const current = { theme: 'dark' as const, accent: 'green' as const, density: 'spacious' as const }

  const next = setPref('accent', 'orange', current, storage)

  assert.equal(next.theme, 'dark')
  assert.equal(next.accent, 'orange')
  assert.equal(next.density, 'spacious')
  // Only the changed key is written to storage by this call.
  assert.equal(storage.getItem('daa.accent'), 'orange')
  assert.equal(storage.getItem('daa.theme'), null)
})
