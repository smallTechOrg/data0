/**
 * starters.test.mjs — logic tests for the C37 session-start starter helpers:
 * payload coercion and the once-per-mount memoizing loader that backs the
 * "Try asking:" block (spec/capabilities/suggested-questions.md).
 *
 * Deliberately a plain `.mjs` file (not `.test.ts`): the repo's tsconfig has no
 * `allowImportingTsExtensions`, so every existing `.test.ts` carries a known
 * TS5097 for its `./x.ts` import — this file stays OUTSIDE the tsconfig
 * `include` globs so `npx tsc --noEmit` keeps its pre-existing error count.
 * Node's type-stripping loads the `.ts` module it imports just the same.
 *
 * Run with: node --experimental-strip-types --test src/lib/starters.test.mjs
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  MAX_STARTERS,
  coerceStarterQuestions,
  createStartersLoader,
} from './starters.ts'

// --- coerceStarterQuestions -------------------------------------------------

test('coerceStarterQuestions returns the trimmed questions from a well-formed payload', () => {
  const out = coerceStarterQuestions({ questions: [' What drives revenue? ', 'Top regions?'] })
  assert.deepEqual(out, ['What drives revenue?', 'Top regions?'])
})

test('coerceStarterQuestions caps the list at MAX_STARTERS (3)', () => {
  const out = coerceStarterQuestions({ questions: ['a', 'b', 'c', 'd', 'e'] })
  assert.equal(MAX_STARTERS, 3)
  assert.deepEqual(out, ['a', 'b', 'c'])
})

test('coerceStarterQuestions drops empty/whitespace-only and non-string entries', () => {
  const out = coerceStarterQuestions({ questions: ['', '   ', 42, null, { q: 'x' }, 'keep me'] })
  assert.deepEqual(out, ['keep me'])
})

test('coerceStarterQuestions returns [] for a malformed payload (null / non-object / non-array questions / missing key)', () => {
  assert.deepEqual(coerceStarterQuestions(null), [])
  assert.deepEqual(coerceStarterQuestions(undefined), [])
  assert.deepEqual(coerceStarterQuestions('nope'), [])
  assert.deepEqual(coerceStarterQuestions({ questions: 'not-an-array' }), [])
  assert.deepEqual(coerceStarterQuestions({}), [])
})

// --- createStartersLoader ---------------------------------------------------

test('loader fetches ONCE and reuses the cached result on later calls (New-session reset reuses, no refetch)', async () => {
  let calls = 0
  const load = createStartersLoader(async () => {
    calls += 1
    return { questions: ['q1', 'q2'] }
  })

  assert.deepEqual(await load(), ['q1', 'q2'])
  assert.deepEqual(await load(), ['q1', 'q2'])
  assert.deepEqual(await load(), ['q1', 'q2'])
  assert.equal(calls, 1)
})

test('loader shares one in-flight fetch across concurrent calls (StrictMode double-effect safe)', async () => {
  let calls = 0
  let release = () => {}
  const gate = new Promise(resolve => {
    release = () => resolve(undefined)
  })
  const load = createStartersLoader(async () => {
    calls += 1
    await gate
    return { questions: ['only once'] }
  })

  const first = load()
  const second = load()
  release()
  assert.deepEqual(await first, ['only once'])
  assert.deepEqual(await second, ['only once'])
  assert.equal(calls, 1)
})

test('loader resolves [] on fetch failure — never throws — and caches the failure (no retry storm)', async () => {
  let calls = 0
  const load = createStartersLoader(async () => {
    calls += 1
    throw new Error('404 until the backend slice lands')
  })

  assert.deepEqual(await load(), [])
  assert.deepEqual(await load(), [])
  assert.equal(calls, 1)
})

test('loader coerces an untrusted payload (caps at 3, drops junk) before caching', async () => {
  const load = createStartersLoader(async () => ({
    questions: ['a', '', 'b', 7, 'c', 'd'],
  }))
  assert.deepEqual(await load(), ['a', 'b', 'c'])
})

test('loader resolves [] for an empty questions list (the UI hides the block)', async () => {
  const load = createStartersLoader(async () => ({ questions: [] }))
  assert.deepEqual(await load(), [])
})
