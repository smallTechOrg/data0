/**
 * dashboardLayout.test.mjs — logic tests for the Dashboard tab's pure layout
 * helpers (C40, Phase 15). Pins the contract vector from spec/api.md.
 *
 * Plain `.mjs` outside the tsconfig `include` (same precedent as starters.test.mjs).
 *
 * Run with: node --experimental-strip-types --test src/lib/dashboardLayout.test.mjs
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  GRID_COLUMNS,
  moveWidget,
  moveWidgetBy,
  orderedByPosition,
  orderedByPriority,
  packByPriority,
  gridWidgets,
  packLayout,
  setWidth,
  toLayoutPayload,
} from './dashboardLayout.ts'

const W = (id, kind, layout) => ({ id, kind, layout })

function rects(widgets) {
  return widgets.map(w => [w.id, w.layout.x, w.layout.y, w.layout.w, w.layout.h])
}

function assertValid(widgets) {
  for (const w of widgets) {
    const l = w.layout
    assert.ok(Number.isInteger(l.x) && l.x >= 0, 'x >= 0')
    assert.ok(Number.isInteger(l.y) && l.y >= 0, 'y >= 0')
    assert.ok(l.w >= 1 && l.h >= 1, 'w,h >= 1')
    assert.ok(l.x + l.w <= GRID_COLUMNS, 'within 12 columns')
  }
  for (let i = 0; i < widgets.length; i += 1) {
    for (let j = i + 1; j < widgets.length; j += 1) {
      const a = widgets[i].layout
      const b = widgets[j].layout
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
      assert.equal(overlap, false, `${widgets[i].id} overlaps ${widgets[j].id}`)
    }
  }
}

const VECTOR_KINDS = ['kpi', 'kpi', 'kpi', 'kpi', 'chart', 'chart', 'table']
const vector = () => VECTOR_KINDS.map((k, i) => W(`w${i + 1}`, k))

test('packLayout equals the spec/api.md contract vector', () => {
  const packed = packLayout(vector())
  assert.deepEqual(rects(packed), [
    ['w1', 0, 0, 3, 2],
    ['w2', 3, 0, 3, 2],
    ['w3', 6, 0, 3, 2],
    ['w4', 9, 0, 3, 2],
    ['w5', 0, 2, 6, 5],
    ['w6', 6, 2, 6, 5],
    ['w7', 0, 7, 12, 6],
  ])
})

test('packByPriority equals the spec/api.md v2 contract vector', () => {
  const packed = packByPriority([
    { id: 'kp2', kind: 'kpi', priority: 2 },
    { id: 'kp1', kind: 'kpi', priority: 1 },
    { id: 'ch4', kind: 'chart', priority: 4 },
    { id: 'tb3', kind: 'table', priority: 3 },
    { id: 'ch5', kind: 'chart', priority: 5 },
  ])
  assert.deepEqual(rects(packed), [
    ['kp1', 0, 0, 3, 2],
    ['kp2', 3, 0, 3, 2],
    ['tb3', 0, 2, 12, 6],
    ['ch4', 0, 8, 6, 5],
    ['ch5', 6, 8, 6, 5],
  ])
  assertValid(packed)
})

test('packByPriority with absent priorities keeps the v1 vector', () => {
  assert.deepEqual(rects(packByPriority(vector())), rects(packLayout(vector())))
})

test('orderedByPriority puts KPIs first, then others merged by priority', () => {
  const ids = orderedByPriority([
    { id: 'c1', kind: 'chart', priority: 1 },
    { id: 'k9', kind: 'kpi', priority: 9 },
    { id: 't2', kind: 'table', priority: 2 },
  ]).map(w => w.id)
  assert.deepEqual(ids, ['k9', 'c1', 't2'])
})

test('packLayout honours existing w/h and does not hoist kinds', () => {
  const packed = packLayout([
    W('t', 'table'),
    W('k', 'kpi'),
    W('c', 'chart', { x: 0, y: 0, w: 4, h: 3 }),
  ])
  assert.deepEqual(rects(packed), [
    ['t', 0, 0, 12, 6],
    ['k', 0, 6, 3, 2],
    ['c', 3, 6, 4, 3],
  ])
})

test('moveWidget moves the dragged widget before the target and re-packs', () => {
  const widgets = packLayout(vector())
  const moved = moveWidget(widgets, 'w7', 'w1')
  assert.deepEqual(
    orderedByPosition(moved).map(w => w.id),
    ['w7', 'w1', 'w2', 'w3', 'w4', 'w5', 'w6'],
  )
  assertValid(moved)
  assert.deepEqual(moved.find(w => w.id === 'w7').layout, { x: 0, y: 0, w: 12, h: 6 })
})

test('moveWidget forward drop lands immediately before the target', () => {
  const widgets = packLayout(vector())
  const moved = moveWidget(widgets, 'w1', 'w4')
  assert.deepEqual(
    orderedByPosition(moved).map(w => w.id),
    ['w2', 'w3', 'w1', 'w4', 'w5', 'w6', 'w7'],
  )
  assertValid(moved)
})

test('moveWidget self-drop and unknown ids are no-ops', () => {
  const widgets = packLayout(vector())
  assert.deepEqual(moveWidget(widgets, 'w2', 'w2'), widgets)
  assert.deepEqual(moveWidget(widgets, 'nope', 'w2'), widgets)
  assert.deepEqual(moveWidget(widgets, 'w2', 'nope'), widgets)
})

test('moveWidgetBy shifts by delta, clamps at the ends, ignores unknown ids', () => {
  const widgets = packLayout(vector())
  const later = moveWidgetBy(widgets, 'w1', 1)
  assert.deepEqual(
    orderedByPosition(later).map(w => w.id).slice(0, 3),
    ['w2', 'w1', 'w3'],
  )
  assert.deepEqual(moveWidgetBy(widgets, 'w1', -1), widgets)
  assert.deepEqual(moveWidgetBy(widgets, 'w7', 1), widgets)
  assert.deepEqual(moveWidgetBy(widgets, 'nope', 1), widgets)
  assertValid(later)
})

test('setWidth changes only the width and re-packs without overlap', () => {
  const widgets = packLayout(vector())
  const wide = setWidth(widgets, 'w1', 12)
  const w1 = wide.find(w => w.id === 'w1')
  assert.equal(w1.layout.w, 12)
  assert.equal(w1.layout.h, 2)
  assertValid(wide)
  const narrow = setWidth(wide, 'w5', 3)
  assert.equal(narrow.find(w => w.id === 'w5').layout.w, 3)
  assert.equal(narrow.find(w => w.id === 'w5').layout.h, 5)
  assertValid(narrow)
  assert.deepEqual(setWidth(widgets, 'nope', 6), widgets)
})

test('toLayoutPayload lists every id exactly once with integer coordinates', () => {
  const payload = toLayoutPayload(packLayout(vector()))
  assert.equal(payload.length, 7)
  assert.equal(new Set(payload.map(p => p.id)).size, 7)
  for (const p of payload) {
    assert.deepEqual(Object.keys(p).sort(), ['h', 'id', 'w', 'x', 'y'])
    for (const k of ['x', 'y', 'w', 'h']) assert.ok(Number.isInteger(p[k]))
  }
})

test('randomized widget sets never overlap or exceed 12 columns', () => {
  let seed = 12345
  const rand = n => {
    seed = (seed * 1664525 + 1013904223) % 4294967296
    return seed % n
  }
  const kinds = ['kpi', 'chart', 'table']
  for (let round = 0; round < 200; round += 1) {
    const count = 1 + rand(12)
    let widgets = packLayout(
      Array.from({ length: count }, (_, i) =>
        W(`r${i}`, kinds[rand(3)], rand(2) ? { x: 0, y: 0, w: 1 + rand(12), h: 1 + rand(8) } : undefined),
      ),
    )
    assertValid(widgets)
    for (let step = 0; step < 6; step += 1) {
      const a = widgets[rand(count)].id
      const b = widgets[rand(count)].id
      const op = rand(3)
      if (op === 0) widgets = moveWidget(widgets, a, b)
      else if (op === 1) widgets = moveWidgetBy(widgets, a, rand(5) - 2)
      else widgets = setWidth(widgets, a, [3, 6, 12][rand(3)])
      assert.equal(widgets.length, count)
      assertValid(widgets)
    }
  }
})

test('gridWidgets closes the hole left by headline KPIs and keeps stored layouts', () => {
  const widgets = [
    { id: 'k1', kind: 'kpi', layout: { x: 0, y: 0, w: 3, h: 2 } },
    { id: 'k2', kind: 'kpi', layout: { x: 3, y: 0, w: 3, h: 2 } },
    { id: 'c1', kind: 'chart', layout: { x: 6, y: 0, w: 6, h: 5 } },
    { id: 'c2', kind: 'chart', layout: { x: 0, y: 2, w: 6, h: 5 } },
    { id: 't1', kind: 'table', layout: { x: 0, y: 7, w: 12, h: 6 } },
  ]
  const got = gridWidgets(widgets, new Set(['k1', 'k2']))
  assert.deepEqual(
    got.map(w => [w.id, w.layout.x, w.layout.y]),
    [['c1', 0, 0], ['c2', 6, 0], ['t1', 0, 5]],
  )
  assert.deepEqual(widgets[2].layout, { x: 6, y: 0, w: 6, h: 5 })
})

test('gridWidgets keeps a KPI beyond the headline row', () => {
  const widgets = [
    { id: 'k1', kind: 'kpi', layout: { x: 0, y: 0, w: 3, h: 2 } },
    { id: 'k5', kind: 'kpi', layout: { x: 3, y: 0, w: 3, h: 2 } },
  ]
  assert.deepEqual(gridWidgets(widgets, new Set(['k1'])).map(w => [w.id, w.layout.x]), [['k5', 0]])
})
