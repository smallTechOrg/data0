/**
 * dashboardPriority.test.mjs — pure priority helpers (C41, Phase 16).
 * Run with: node --experimental-strip-types --test src/lib/dashboardPriority.test.mjs
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  headlineKpis,
  reorderPriority,
  reorderPriorityBy,
  sortByPriority,
} from './dashboardPriority.ts'

const W = (id, kind, priority) => ({ id, kind, priority })
const set = () => [
  W('c', 'chart', 3),
  W('k2', 'kpi', 2),
  W('k1', 'kpi', 1),
  W('t', 'table', 4),
  W('k3', 'kpi', 5),
]

test('sortByPriority orders by rank, stable, missing last', () => {
  assert.deepEqual(sortByPriority(set()).map(w => w.id), ['k1', 'k2', 'c', 't', 'k3'])
  assert.deepEqual(
    sortByPriority([W('a', 'kpi'), W('b', 'kpi', 1), W('c', 'kpi')]).map(w => w.id),
    ['b', 'a', 'c'],
  )
})

test('reorderPriority moves from before to', () => {
  assert.deepEqual(reorderPriority(set(), 't', 'k1'), ['t', 'k1', 'k2', 'c', 'k3'])
  assert.deepEqual(reorderPriority(set(), 'k1', 't'), ['k2', 'c', 'k1', 't', 'k3'])
})

test('reorderPriority self/unknown is a no-op returning every id once', () => {
  const same = ['k1', 'k2', 'c', 't', 'k3']
  assert.deepEqual(reorderPriority(set(), 'c', 'c'), same)
  assert.deepEqual(reorderPriority(set(), 'nope', 'c'), same)
  assert.deepEqual(reorderPriority(set(), 'c', 'nope'), same)
  assert.deepEqual(reorderPriority([], 'a', 'b'), [])
})

test('reorderPriorityBy shifts and clamps', () => {
  assert.deepEqual(reorderPriorityBy(set(), 'k1', 1), ['k2', 'k1', 'c', 't', 'k3'])
  assert.deepEqual(reorderPriorityBy(set(), 'k1', -1), ['k1', 'k2', 'c', 't', 'k3'])
  assert.deepEqual(reorderPriorityBy(set(), 'k3', 9), ['k1', 'k2', 'c', 't', 'k3'])
  assert.deepEqual(reorderPriorityBy(set(), 'k3', -9), ['k3', 'k1', 'k2', 'c', 't'])
  assert.deepEqual(reorderPriorityBy(set(), 'nope', 1), ['k1', 'k2', 'c', 't', 'k3'])
})

test('headlineKpis returns only KPIs by priority, capped at 4', () => {
  assert.deepEqual(headlineKpis(set()).map(w => w.id), ['k1', 'k2', 'k3'])
  const many = Array.from({ length: 6 }, (_, i) => W(`k${6 - i}`, 'kpi', 6 - i))
  assert.deepEqual(headlineKpis(many).map(w => w.id), ['k1', 'k2', 'k3', 'k4'])
  assert.equal(headlineKpis(many, 2).length, 2)
  assert.deepEqual(headlineKpis([W('c', 'chart', 1)]), [])
})
