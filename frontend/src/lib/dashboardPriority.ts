/**
 * dashboardPriority.ts — pure priority helpers for the Dashboard tab (C41, Phase 16).
 *
 * No React, no imports (loaded directly by `node --test`). Priority is a dense
 * global rank 1..N; the "Key insights" headline row is the top KPIs by rank.
 */

export const HEADLINE_MAX = 4

export interface PriorityWidget {
  id: string
  kind: 'kpi' | 'chart' | 'table'
  priority?: number | null
}

const rankOf = (w: PriorityWidget): number =>
  typeof w.priority === 'number' && Number.isFinite(w.priority) ? w.priority : Number.MAX_SAFE_INTEGER

/** Widgets sorted by priority asc (stable; missing priority sorts last). */
export function sortByPriority<T extends PriorityWidget>(widgets: readonly T[]): T[] {
  return widgets
    .map((widget, index) => ({ widget, index }))
    .sort((a, b) => rankOf(a.widget) - rankOf(b.widget) || a.index - b.index)
    .map(e => e.widget)
}

/**
 * Move `fromId` immediately BEFORE `toId` in the priority ordering and return
 * the full `priority_order` id list (most important first) for
 * PATCH /dashboards/{id}. Self-move or unknown ids return the current order.
 */
export function reorderPriority(
  widgets: readonly PriorityWidget[],
  fromId: string,
  toId: string,
): string[] {
  const ids = sortByPriority(widgets).map(w => w.id)
  if (fromId === toId || !ids.includes(fromId) || !ids.includes(toId)) return ids
  const rest = ids.filter(id => id !== fromId)
  rest.splice(rest.indexOf(toId), 0, fromId)
  return rest
}

/** Shift `id` by `delta` positions (negative = more important), clamped; returns the id list. */
export function reorderPriorityBy(
  widgets: readonly PriorityWidget[],
  id: string,
  delta: number,
): string[] {
  const ids = sortByPriority(widgets).map(w => w.id)
  const from = ids.indexOf(id)
  if (from < 0) return ids
  const to = Math.max(0, Math.min(ids.length - 1, from + delta))
  if (to === from) return ids
  ids.splice(from, 1)
  ids.splice(to, 0, id)
  return ids
}

/** Top KPIs by priority (default 4) forming the numbered "Key insights" row. */
export function headlineKpis<T extends PriorityWidget>(
  widgets: readonly T[],
  max: number = HEADLINE_MAX,
): T[] {
  return sortByPriority(widgets.filter(w => w.kind === 'kpi')).slice(0, Math.max(0, max))
}
