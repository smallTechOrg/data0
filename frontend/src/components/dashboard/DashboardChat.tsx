'use client'

import { useEffect, useRef, useState } from 'react'
import { api, ApiError, type DashboardChatResponse } from '@/lib/api'

interface Msg {
  role: 'user' | 'assistant'
  text: string
  changed?: boolean
}

const SUGGESTIONS = [
  'Add a chart of the top 10 categories',
  'Make the main chart a line chart',
  'Remove the table',
  'Show averages instead of totals',
]

/**
 * Chat that edits the open dashboard: each message is sent to the server, which
 * revises the dashboard spec; the new dashboard replaces the one on screen.
 */
export function DashboardChat({
  dashboardId,
  onUpdated,
}: {
  dashboardId: string
  onUpdated: (result: DashboardChatResponse) => void
}) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  // A different dashboard starts a fresh conversation.
  useEffect(() => {
    setMessages([])
    setText('')
  }, [dashboardId])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, busy])

  const send = async (raw: string) => {
    const message = raw.trim()
    if (!message || busy) return
    setMessages(m => [...m, { role: 'user', text: message }])
    setText('')
    setBusy(true)
    try {
      const res = await api.chatDashboard(dashboardId, message)
      setMessages(m => [...m, { role: 'assistant', text: res.reply, changed: res.changed }])
      if (res.changed) onUpdated(res)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Couldn't reach the server — is the server running?"
      setMessages(m => [...m, { role: 'assistant', text: msg }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dx-pane">
      <div className="dx-chat-body" role="log" aria-live="polite">
        {messages.length === 0 && (
          <div className="space-y-1.5">
            <p className="text-xs opacity-60">Try:</p>
            {SUGGESTIONS.map(s => (
              <button key={s} type="button" className="dx-chip" onClick={() => void send(s)} disabled={busy}>
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'dx-msg dx-msg-user' : 'dx-msg dx-msg-ai'}>
            {m.text}
            {m.changed && <span className="dx-updated">Dashboard updated</span>}
          </div>
        ))}
        {busy && <div className="dx-msg dx-msg-ai opacity-70">Updating the dashboard…</div>}
        <div ref={endRef} />
      </div>

      <form
        className="dx-chat-form"
        onSubmit={e => {
          e.preventDefault()
          void send(text)
        }}
      >
        <input
          value={text}
          maxLength={1000}
          onChange={e => setText(e.target.value)}
          placeholder="e.g. add revenue by region"
          aria-label="Message"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !text.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
