'use client'

import type { AiInsight, DashboardData } from '@/lib/api'

const TONE: Record<AiInsight['tone'], { icon: string; cls: string }> = {
  positive: { icon: '↗', cls: 'dx-tone-pos' },
  negative: { icon: '↘', cls: 'dx-tone-neg' },
  warning: { icon: '!', cls: 'dx-tone-warn' },
  neutral: { icon: '•', cls: 'dx-tone-neu' },
}

/** AI insights: data overview + findings computed from the data (no invented causes). */
export function InsightsPanel({ data }: { data: DashboardData | null }) {
  if (!data) return <div className="dx-pane p-4 text-xs opacity-60">Loading insights…</div>
  const ov = data.overview
  const insights = data.ai_insights ?? []
  return (
    <div className="dx-pane">
      <div className="dx-chat-body">
        {ov && (
          <div className="dx-ov">
            <div>
              <b>{ov.rows.toLocaleString()}</b>
              <span>records</span>
            </div>
            <div>
              <b>{ov.columns}</b>
              <span>columns</span>
            </div>
            <div>
              <b>{ov.completeness}%</b>
              <span>complete</span>
            </div>
            <div>
              <b>{ov.duplicate_rows.toLocaleString()}</b>
              <span>duplicates</span>
            </div>
          </div>
        )}
        <h4 className="text-xs font-semibold uppercase tracking-wide opacity-60">What the data shows</h4>
        {insights.length === 0 ? (
          <p className="text-xs opacity-60">No notable patterns found for the current widgets.</p>
        ) : (
          <ul className="space-y-2">
            {insights.map((i, n) => {
              const t = TONE[i.tone] ?? TONE.neutral
              return (
                <li key={n} className="dx-insight">
                  <span className={`dx-insight-icon ${t.cls}`} aria-hidden>
                    {t.icon}
                  </span>
                  <span>{i.text}</span>
                </li>
              )
            })}
          </ul>
        )}
        <p className="text-[11px] opacity-45">Computed directly from your data. Ask the chat to dig deeper.</p>
      </div>
    </div>
  )
}
