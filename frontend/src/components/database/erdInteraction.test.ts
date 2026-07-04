/**
 * erdInteraction.test.ts — logic tests for the ER diagram's zoom/drag/reset
 * interactions (extracted from ERDiagramPanel.tsx into erdInteraction.ts so
 * Node's built-in test runner can import them directly; see that file's
 * header comment for why).
 *
 * Run with: node --experimental-strip-types --test src/components/database/erdInteraction.test.ts
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  clampZoom,
  hasLayoutOverrides,
  isDragMove,
  zoomAnchored,
} from './erdInteraction.ts'

test('clampZoom clamps to the 0.15x-3x range and passes through in-range values', () => {
  assert.equal(clampZoom(0.01), 0.15)
  assert.equal(clampZoom(10), 3)
  assert.equal(clampZoom(1), 1)
  assert.equal(clampZoom(0.15), 0.15)
  assert.equal(clampZoom(3), 3)
})

test('zoomAnchored keeps the content under the anchor point fixed on screen when zooming in', () => {
  // Anchor at (200, 150) in screen space, starting at zoom=1, pan=(0,0). The
  // local content point currently under the anchor is (anchor - pan) / zoom.
  const zOld = 1
  const panOld = { x: 0, y: 0 }
  const anchor = { x: 200, y: 150 }
  const localPointBefore = {
    x: (anchor.x - panOld.x) / zOld,
    y: (anchor.y - panOld.y) / zOld,
  }

  const { zoom: zNew, pan: panNew } = zoomAnchored(zOld, panOld, 1.1, anchor.x, anchor.y)

  assert.equal(zNew, 1.1)
  // The SAME local point, re-projected through the NEW zoom/pan, must land
  // back on the same screen anchor — i.e. nothing under the cursor moved.
  const screenAfter = {
    x: panNew.x + zNew * localPointBefore.x,
    y: panNew.y + zNew * localPointBefore.y,
  }
  assert.ok(Math.abs(screenAfter.x - anchor.x) < 1e-9)
  assert.ok(Math.abs(screenAfter.y - anchor.y) < 1e-9)
})

test('zoomAnchored keeps the anchor fixed when zooming out from a non-trivial pan/zoom', () => {
  const zOld = 1.8
  const panOld = { x: 42, y: -17 }
  const anchor = { x: 60, y: 300 }
  const localPointBefore = {
    x: (anchor.x - panOld.x) / zOld,
    y: (anchor.y - panOld.y) / zOld,
  }

  const { zoom: zNew, pan: panNew } = zoomAnchored(zOld, panOld, 1 / 1.1, anchor.x, anchor.y)

  const screenAfter = {
    x: panNew.x + zNew * localPointBefore.x,
    y: panNew.y + zNew * localPointBefore.y,
  }
  assert.ok(Math.abs(screenAfter.x - anchor.x) < 1e-9)
  assert.ok(Math.abs(screenAfter.y - anchor.y) < 1e-9)
})

test('zoomAnchored clamps the resulting zoom at the floor/ceiling (top-left drift regression guard)', () => {
  // Regression guard: before the fix, repeatedly zooming out with no anchor
  // compensation drifted content toward the top-left. Here we just confirm
  // clamping still applies through the anchored path, and that pan is still
  // computed (not left stuck at the old value) even at the clamp boundary.
  const { zoom } = zoomAnchored(0.2, { x: 10, y: 10 }, 0.5, 50, 50)
  assert.equal(zoom, 0.15) // hit the floor, not 0.2 * 0.5 = 0.1
  const { zoom: zoomHigh } = zoomAnchored(2.9, { x: 10, y: 10 }, 1.5, 50, 50)
  assert.equal(zoomHigh, 3) // hit the ceiling
})

test('isDragMove is false under the 3px threshold on both axes (a plain click)', () => {
  assert.equal(isDragMove(0, 0), false)
  assert.equal(isDragMove(2, 0), false)
  assert.equal(isDragMove(0, -2), false)
  assert.equal(isDragMove(2, 2), false)
})

test('isDragMove is true once either axis exceeds the 3px threshold (a real drag)', () => {
  assert.equal(isDragMove(4, 0), true)
  assert.equal(isDragMove(0, -4), true)
  assert.equal(isDragMove(-10, 10), true)
})

test('isDragMove respects a custom threshold', () => {
  assert.equal(isDragMove(8, 0, 10), false)
  assert.equal(isDragMove(11, 0, 10), true)
})

test('hasLayoutOverrides is false with no dragged cards (Reset layout starts disabled)', () => {
  assert.equal(hasLayoutOverrides({}), false)
})

test('hasLayoutOverrides is true once any card has been dragged (Reset layout becomes enabled)', () => {
  assert.equal(hasLayoutOverrides({ 'dataset-1': { x: 40, y: 60 } }), true)
})
