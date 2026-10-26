'use client'

import type { ChartWidgetDef, WidgetData } from '@/lib/api'
import { EChart } from '@/components/analyse/ChartRender'
import { WidgetError } from './KpiWidget'

/** Chart body — the server's ECharts option rendered by the shared EChart renderer. */
export function ChartWidget({
  def,
  data,
  index,
}: {
  def: ChartWidgetDef
  data: WidgetData | undefined
  index: number
}) {
  if (!data) return <div className="h-full animate-pulse rounded bg-gray-100" aria-label="Loading" />
  if (data.status === 'error') return <WidgetError message={data.message} />
  if (data.kind !== 'chart') return <WidgetError message="Unexpected data for this widget." />
  if (!data.option || !('series' in data.option)) {
    return <WidgetError message={`No chart could be drawn for "${def.title}".`} />
  }
  return <EChart option={data.option} index={index} />
}
