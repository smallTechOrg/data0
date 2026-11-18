'use client'

import { useState } from 'react'
import type { DashboardWidget } from '@/lib/api'

/** Marks server-written text so it is never mistaken for the agent's own words. */
export function AutoTag() {
  return (
    <span
      title="Written automatically from the widget's settings"
      className="ml-1 rounded border border-gray-200 px-1 text-[10px] text-gray-400"
    >
      auto
    </span>
  )
}

/** A widget's why-it-matters line and, for charts, a collapsible chart-type justification. */
export function WidgetDescription({ widget }: { widget: DashboardWidget }) {
  const [showWhy, setShowWhy] = useState(true)
  const rationale = widget.kind === 'chart' ? widget.chart_rationale : null
  if (!widget.description && !rationale) return null
  const article = widget.kind === 'chart' && widget.chart.type === 'area' ? 'an' : 'a'
  return (
    <div className="border-b border-gray-100 px-3 py-1.5 text-xs leading-snug">
      {widget.description && (
        <p className="line-clamp-2 text-gray-600" title={widget.description}>
          {widget.description}
          {widget.description_source === 'auto' && <AutoTag />}
        </p>
      )}
      {widget.kind === 'chart' && rationale && (
        <p className="mt-0.5 flex items-start gap-1 text-[11px] text-gray-400">
          <button
            type="button"
            aria-expanded={showWhy}
            aria-label={`${showWhy ? 'Hide' : 'Show'} why this chart type was chosen`}
            onClick={() => setShowWhy(v => !v)}
            className="shrink-0 rounded px-0.5 hover:bg-gray-100 hover:text-gray-700"
          >
            {showWhy ? '▾' : '▸'}
          </button>
          <span className={showWhy ? 'line-clamp-2' : ''} title={rationale}>
            Why {article} {widget.chart.type} chart{showWhy ? `: ${rationale}` : ''}
          </span>
        </p>
      )}
    </div>
  )
}
