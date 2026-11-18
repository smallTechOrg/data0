'use client'

import type { KpiWidgetDef, WidgetData } from '@/lib/api'

/** KPI body — large formatted value + caption; an empty value shows "—". */
export function KpiWidget({ def, data }: { def: KpiWidgetDef; data: WidgetData | undefined }) {
  if (!data) return <div className="h-full animate-pulse rounded bg-gray-100" aria-label="Loading" />
  if (data.status === 'error') return <WidgetError message={data.message} />
  if (data.kind !== 'kpi') return <WidgetError message="Unexpected data for this widget." />
  const text = data.value === null || data.value === undefined ? '—' : data.formatted || '—'
  const caption = data.caption ?? `${def.kpi.agg}${def.kpi.field ? ` of ${def.kpi.field}` : ' of rows'}`
  return (
    <div className="flex h-full flex-col justify-center">
      <div className="truncate text-3xl font-bold tracking-tight text-gray-900" title={text}>
        {text}
      </div>
      <div className="mt-1 truncate text-xs text-gray-500">{caption}</div>
    </div>
  )
}

/** Red inline panel for a widget whose computation failed (siblings unaffected). */
export function WidgetError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex h-full items-center rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
    >
      {message}
    </div>
  )
}
