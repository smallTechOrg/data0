/**
 * dashboardLayout.ts — pure layout helpers for the Dashboard tab (C40, Phase 15).
 *
 * No React, no imports: the module is loaded directly by `node --test`
 * (see dashboardLayout.test.mjs). `packLayout` is the SAME first-fit algorithm
 * as the backend's `assign_layout` (spec/api.md -> "Default layout assignment"),
 * pinned by the contract vector asserted in both test suites.
 *
 * The "ordering" of a dashboard is its widgets sorted by (y, x). Every
 * operation reorders that list and then RE-PACKS, so the result is always a
 * valid layout (12 columns, no overlap) the backend's PATCH will accept.
 */

export const GRID_COLUMNS = 12

export type WidgetKind = 'kpi' | 'chart' | 'table'

export interface LayoutRect {
  x: number
  y: number
  w: number
  h: number
}

/** Minimal widget shape these helpers need; the API's DashboardWidget satisfies it. */
export interface LayoutWidget {
  id: string
  kind: WidgetKind
  layout?: LayoutRect | null
}

export interface LayoutPayloadItem extends LayoutRect {
  id: string
}

/** Default sizes by kind (w x h) from the contract. */
export const DEFAULT_SIZE: Record<WidgetKind, { w: number; h: number }> = {
  kpi: { w: 3, h: 2 },
  chart: { w: 6, h: 5 },
  table: { w: 12, h: 6 },
}

/** Widths offered by the S / M / L size control. */
export const WIDTH_PRESETS = { S: 3, M: 6, L: 12 } as const

function sizeOf(widget: LayoutWidget): { w: number; h: number } {
  const def = DEFAULT_SIZE[widget.kind] ?? DEFAULT_SIZE.chart
  const l = widget.layout
  const w = l && Number.isInteger(l.w) && l.w >= 1 ? Math.min(l.w, GRID_COLUMNS) : def.w
  const h = l && Number.isInteger(l.h) && l.h >= 1 ? l.h : def.h
  return { w, h }
}

/** Widgets in reading order: ascending y, then ascending x (stable). */
export function orderedByPosition<T extends LayoutWidget>(widgets: readonly T[]): T[] {
  return widgets
    .map((widget, index) => ({ widget, index }))
    .sort((a, b) => {
      const ay = a.widget.layout?.y ?? 0
      const by = b.widget.layout?.y ?? 0
      if (ay !== by) return ay - by
      const ax = a.widget.layout?.x ?? 0
      const bx = b.widget.layout?.x ?? 0
      if (ax !== bx) return ax - bx
      return a.index - b.index
    })
    .map(entry => entry.widget)
}

/**
 * First-fit, row-major packing in the GIVEN order (no kind hoisting — that only
 * applies at creation, server-side). Each widget keeps its existing w/h
 * (defaults by kind when absent) and takes the smallest y, then smallest x,
 * where it fits inside 12 columns and overlaps nothing already placed.
 * Returns new widget objects in the same order as the input.
 */
export function packLayout<T extends LayoutWidget>(widgets: readonly T[]): T[] {
  const placed: LayoutRect[] = []
  const overlaps = (x: number, y: number, w: number, h: number): boolean =>
    placed.some(p => x < p.x + p.w && p.x < x + w && y < p.y + p.h && p.y < y + h)

  return widgets.map(widget => {
    const { w, h } = sizeOf(widget)
    let spot: LayoutRect | null = null
    for (let y = 0; spot === null; y += 1) {
      for (let x = 0; x + w <= GRID_COLUMNS; x += 1) {
        if (!overlaps(x, y, w, h)) {
          spot = { x, y, w, h }
          break
        }
      }
    }
    placed.push(spot)
    return { ...widget, layout: spot }
  })
}

/**
 * Drop semantics: move `fromId` so it sits immediately BEFORE `toId` in the
 * ordering, then re-pack. Self-drop or an unknown id returns the widgets
 * unchanged (same array contents, no re-pack).
 */
export function moveWidget<T extends LayoutWidget>(
  widgets: readonly T[],
  fromId: string,
  toId: string,
): T[] {
  if (fromId === toId) return [...widgets]
  const order = orderedByPosition(widgets)
  const from = order.find(w => w.id === fromId)
  if (!from || !order.some(w => w.id === toId)) return [...widgets]
  const rest = order.filter(w => w.id !== fromId)
  const at = rest.findIndex(w => w.id === toId)
  rest.splice(at, 0, from)
  return packLayout(rest)
}

/**
 * Keyboard move: shift `id` by `delta` positions in the ordering (negative =
 * earlier), clamped to the ends, then re-pack. Unknown id or no movement
 * returns the widgets unchanged.
 */
export function moveWidgetBy<T extends LayoutWidget>(
  widgets: readonly T[],
  id: string,
  delta: number,
): T[] {
  const order = orderedByPosition(widgets)
  const index = order.findIndex(w => w.id === id)
  if (index < 0) return [...widgets]
  const target = Math.max(0, Math.min(order.length - 1, index + delta))
  if (target === index) return [...widgets]
  const [item] = order.splice(index, 1)
  order.splice(target, 0, item)
  return packLayout(order)
}

/** Set a widget's width (clamped to 1..12), keep its height, then re-pack in (y, x) order. */
export function setWidth<T extends LayoutWidget>(
  widgets: readonly T[],
  id: string,
  w: number,
): T[] {
  if (!widgets.some(x => x.id === id)) return [...widgets]
  const width = Math.max(1, Math.min(GRID_COLUMNS, Math.trunc(w)))
  const order = orderedByPosition(widgets).map(widget => {
    if (widget.id !== id) return widget
    const { h } = sizeOf(widget)
    const l = widget.layout ?? { x: 0, y: 0, w: width, h }
    return { ...widget, layout: { ...l, w: width, h } }
  })
  return packLayout(order)
}

/** Build the PATCH /dashboards/{id} `layout` body: every widget id exactly once. */
export function toLayoutPayload(widgets: readonly LayoutWidget[]): LayoutPayloadItem[] {
  return widgets.map(widget => {
    const { w, h } = sizeOf(widget)
    return {
      id: widget.id,
      x: widget.layout?.x ?? 0,
      y: widget.layout?.y ?? 0,
      w,
      h,
    }
  })
}

/** 1-based position of a widget in the (y, x) ordering, or 0 if unknown. */
export function positionOf(widgets: readonly LayoutWidget[], id: string): number {
  return orderedByPosition(widgets).findIndex(w => w.id === id) + 1
}
