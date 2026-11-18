'use client'

import type { WidgetData } from '@/lib/api'
import { WidgetError } from './KpiWidget'

function cell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return String(value)
}

/** Table body — scrollable, sticky header, right-aligned numerics, row-count footer. */
export function TableWidget({ data }: { data: WidgetData | undefined }) {
  if (!data) return <div className="h-full animate-pulse rounded bg-gray-100" aria-label="Loading" />
  if (data.status === 'error') return <WidgetError message={data.message} />
  if (data.kind !== 'table') return <WidgetError message="Unexpected data for this widget." />
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto rounded-md border border-gray-200">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-gray-50">
            <tr>
              {data.columns.map(c => (
                <th
                  key={c}
                  scope="col"
                  className="border-b border-gray-200 px-2 py-1.5 text-left font-semibold text-gray-600"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, i) => (
              <tr key={i} className="border-b border-gray-100 last:border-0">
                {row.map((v, j) => (
                  <td
                    key={j}
                    className={`px-2 py-1 text-gray-700 ${typeof v === 'number' ? 'text-right tabular-nums' : ''}`}
                  >
                    {cell(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-1 text-[11px] text-gray-500">
        Showing {data.rows.length} row{data.rows.length === 1 ? '' : 's'}
        {data.truncated ? ' (truncated)' : ''}
      </div>
    </div>
  )
}
