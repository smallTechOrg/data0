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
    <section aria-label="Key insights" className="mb-4">
      <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((kpi, i) => {
          const wd = data?.widgets[kpi.id]
          return (
            <li
              key={kpi.id}
              data-widget-id={kpi.id}
              className={`dx-card dx-kpi flex min-w-0 flex-col p-4 ${i === 0 ? 'dx-kpi-hero' : ''}`}
            >
              <div className="flex items-center gap-2">
                <span aria-label={`Rank ${i + 1}`} className="dx-kpi-rank">
                  {i + 1}
                </span>
                <h4 className="min-w-0 truncate text-xs font-medium opacity-70" title={kpi.title}>
                  {kpi.title}
                </h4>
              </div>
              <div className="mt-3 min-h-[2.5rem]">
                {!wd ? (
                  <div className="h-8 animate-pulse rounded bg-gray-100" aria-label="Loading" />
                ) : wd.status === 'error' ? (
                  <WidgetError message={wd.message} />
                ) : wd.kind === 'kpi' ? (
                  <div className="truncate text-3xl font-bold tracking-tight" title={wd.formatted}>
                    {wd.value === null || wd.value === undefined ? '—' : wd.formatted || '—'}
                  </div>
                ) : (
                  <WidgetError message="Unexpected data for this widget." />
                )}
              </div>
              {kpi.description && (
                <p className="mt-2 text-xs leading-snug opacity-55">
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
