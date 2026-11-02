'use client'

import type { DashboardData, KpiWidgetDef } from '@/lib/api'
import { WidgetError } from './KpiWidget'
import { AutoTag } from './WidgetDescription'

/**
 * "Key insights" headline row (C41): the top KPIs by priority, numbered 1..N by
 * position, each with its value and a one-line why-it-matters. #1 is tinted.
 */
export function KeyInsights({ kpis, data }: { kpis: KpiWidgetDef[]; data: DashboardData | null }) {
  if (kpis.length === 0) return null
  return (
    <section aria-label="Key insights" className="mb-3">
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">Key insights</h3>
      <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((kpi, i) => {
          const wd = data?.widgets[kpi.id]
          return (
            <li
              key={kpi.id}
              data-widget-id={kpi.id}
              className={`flex min-w-0 flex-col rounded-lg border p-3 shadow-sm ${
                i === 0 ? 'border-indigo-300 bg-indigo-100' : 'border-gray-200 bg-white'
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  aria-label={`Rank ${i + 1}`}
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                    i === 0 ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700'
                  }`}
                >
                  {i + 1}
                </span>
                <h4 className="min-w-0 truncate text-xs font-medium text-gray-700" title={kpi.title}>
                  {kpi.title}
                </h4>
              </div>
              <div className="mt-1.5 min-h-[2.25rem]">
                {!wd ? (
                  <div className="h-8 animate-pulse rounded bg-gray-100" aria-label="Loading" />
                ) : wd.status === 'error' ? (
                  <WidgetError message={wd.message} />
                ) : wd.kind === 'kpi' ? (
                  <div className="truncate text-2xl font-bold tracking-tight text-gray-900" title={wd.formatted}>
                    {wd.value === null || wd.value === undefined ? '—' : wd.formatted || '—'}
                  </div>
                ) : (
                  <WidgetError message="Unexpected data for this widget." />
                )}
              </div>
              {kpi.description && (
                <p className="mt-1 text-xs leading-snug text-gray-500">
                  {kpi.description}
                  {kpi.description_source === 'auto' && <AutoTag />}
                </p>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
