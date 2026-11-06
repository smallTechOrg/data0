'use client'

import { useState } from 'react'
import type { DashboardChatResponse, DashboardData } from '@/lib/api'
import { DashboardChat } from './DashboardChat'
import { InsightsPanel } from './InsightsPanel'

/** Right-hand AI workspace: Insights tab + Chat tab (both stay mounted). */
export function WorkspacePanel({
  dashboardId,
  data,
  onUpdated,
}: {
  dashboardId: string
  data: DashboardData | null
  onUpdated: (r: DashboardChatResponse) => void
}) {
  const [tab, setTab] = useState<'insights' | 'chat'>('insights')
  const count = data?.ai_insights?.length ?? 0
  return (
    <aside className="dx-chat" aria-label="AI workspace">
      <div className="dx-chat-head">
        <span className="dx-chat-spark" aria-hidden>
          ✦
        </span>
        <div>
          <h3 className="text-sm font-semibold">AI workspace</h3>
          <p className="text-[11px] opacity-60">Insights from your data, and edit by chat.</p>
        </div>
      </div>
      <div role="tablist" className="dx-tabs">
        <button type="button" role="tab" aria-selected={tab === 'insights'} onClick={() => setTab('insights')}>
          AI Insights{count > 0 && <em>{count}</em>}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'chat'} onClick={() => setTab('chat')}>
          Chat &amp; edit
        </button>
      </div>
      <div className={tab === 'insights' ? 'dx-tabpane' : 'dx-tabpane hidden'}>
        <InsightsPanel data={data} />
      </div>
      <div className={tab === 'chat' ? 'dx-tabpane' : 'dx-tabpane hidden'}>
        <DashboardChat dashboardId={dashboardId} onUpdated={onUpdated} />
      </div>
    </aside>
  )
}
