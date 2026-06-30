'use client'

import { useEffect, useRef, useState } from 'react'

import * as echarts from 'echarts/core'
import {
  BarChart,
  LineChart,
  ScatterChart,
  PieChart,
  HeatmapChart,
  BoxplotChart,
} from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  ScatterChart,
  PieChart,
  HeatmapChart,
  BoxplotChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  CanvasRenderer,
])

/**
 * Inline ECharts chart renderer (C4).
 *
 * The agent captures any chart it builds during analysis and returns it as a
 * JSON STRING (one per chart) on the answer's `charts` array. Each string
 * parses to an ECharts option object `{ title, tooltip, xAxis, yAxis, series, ... }`.
 *
 * We render IMPERATIVELY via `echarts.init(div).setOption(option)` inside a
 * `useEffect`. The ECharts core build is tree-shaken (only the chart/component
 * modules we register above are pulled in), so the static-export bundle stays
 * lean.
 *
 * Robustness:
 *  - Each entry is parsed independently; a malformed JSON entry — or one that is
 *    not an object with a `series` key — is skipped (renders nothing for that
 *    slot) and never crashes the surrounding turn.
 *  - The chart instance is disposed on unmount / before re-render to release it,
 *    and resizes responsively via a ResizeObserver on its container.
 */
export function ChartRender({ charts }: { charts?: string[] }) {
  const options = parseOptions(charts)

  if (options.length === 0) return null

  return (
    <div className="mt-3 space-y-3" aria-label="Charts">
      {options.map((opt, i) => (
        <EChart key={i} option={opt} index={i} />
      ))}
    </div>
  )
}

/** An ECharts option object — opaque to us beyond the required `series` key. */
type EChartsOption = Record<string, unknown>

/** Parse the chart JSON strings, dropping any that are malformed / not options. */
function parseOptions(charts?: string[]): EChartsOption[] {
  if (!Array.isArray(charts)) return []
  const out: EChartsOption[] = []
  for (const raw of charts) {
    if (typeof raw !== 'string' || raw.trim() === '') continue
    try {
      const parsed = JSON.parse(raw) as unknown
      if (!parsed || typeof parsed !== 'object') continue
      // A renderable ECharts option must carry a `series` key.
      if (!('series' in (parsed as Record<string, unknown>))) continue
      out.push(parsed as EChartsOption)
    } catch {
      // Malformed JSON for this entry — skip it, never break the turn.
    }
  }
  return out
}

/** A single chart drawn into a responsive div via ECharts' imperative API. */
function EChart({ option, index }: { option: EChartsOption; index: number }) {
  const ref = useRef<HTMLDivElement>(null)
  // Captured once the chart is initialised, so the toolbar can export it.
  const chartRef = useRef<echarts.ECharts | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const chart = echarts.init(el)
    chartRef.current = chart
    chart.setOption(option)

    // Keep the chart sized to its (responsive) container.
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(el)

    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [option])

  const downloadImage = (format: 'png' | 'jpeg') => {
    const chart = chartRef.current
    if (!chart) return
    try {
      const url = chart.getDataURL({ type: format, pixelRatio: 2, backgroundColor: '#fff' })
      const a = document.createElement('a')
      a.href = url
      a.download = `chart-${index + 1}.${format === 'jpeg' ? 'jpg' : 'png'}`
      a.click()
    } catch {
      /* export failed — no-op */
    }
  }

  const copyPng = async () => {
    const chart = chartRef.current
    if (!chart) return
    try {
      const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' })
      const blob = await (await fetch(url)).blob()
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard-image unsupported (or blocked) — fall back to a PNG download.
      downloadImage('png')
    }
  }

  const btn =
    'rounded border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-medium text-gray-500 hover:bg-gray-50 hover:text-gray-700'

  return (
    <div>
      <div className="mb-1 flex justify-end gap-1.5">
        <button type="button" onClick={() => void copyPng()} className={btn}>
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" onClick={() => downloadImage('png')} className={btn}>
          PNG
        </button>
        <button type="button" onClick={() => downloadImage('jpeg')} className={btn}>
          JPEG
        </button>
      </div>
      <div
        ref={ref}
        role="img"
        aria-label={`Chart ${index + 1}`}
        className="min-h-[18rem] w-full overflow-hidden rounded-md border border-gray-200 bg-white"
      />
    </div>
  )
}
