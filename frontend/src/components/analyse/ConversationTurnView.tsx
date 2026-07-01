'use client'

import type { AskResponse, AskStep } from '@/lib/api'
import { Markdown } from '@/components/analyse/Markdown'
import { ChartRender } from '@/components/analyse/ChartRender'
import { StepsInspector } from '@/components/analyse/StepsInspector'
import { PromptBreakdown } from '@/components/analyse/PromptBreakdown'
import { ClarificationTurn } from '@/components/analyse/ClarificationTurn'

/**
 * Presentational primitive for a single conversation turn, extracted from
 * ConversationCard. PURE: no useEffect and no api / fetch calls — all data
 * arrives via props (the `turn` object + display flags) and all interactions are
 * surfaced as `on*` callbacks. The owning ConversationCard keeps the
 * ask/poll/export logic.
 */

export type TurnStatus = 'pending' | 'answer' | 'clarification' | 'error'

export interface Turn {
  id: string
  question: string
  status: TurnStatus
  answer?: AskResponse
  clarificationQuestion?: string
  /** The original question to re-send on a clarification "answer anyway". */
  originalQuestion?: string
  error?: string
  /**
   * Epoch ms the answer landed, for the "Asked at {time}" meta line. Live
   * answers capture `Date.now()` when the response arrives; hydrated history
   * turns reuse the persisted `created_at` when present, else stay undefined
   * (the "Asked at" prefix is then omitted gracefully).
   */
  answeredAt?: number
  /** Response time in ms (server wall-clock live; row lifespan for history). */
  durationMs?: number
}

export interface ConversationTurnViewProps {
  /** The turn to render (question + pending/answer/clarification/error state). */
  turn: Turn
  /** Whether an answer turn is currently expanded (vs the C32 collapsed preview). */
  expanded: boolean
  /** Whether this turn supports collapse/expand (true only for answer turns). */
  collapsible: boolean
  /** Toggle this turn's expand/collapse state. */
  onToggle: () => void
  /** Re-submit a clarification turn's original question (skip clarification). */
  onResubmitClarification: () => void
  /** Whether an ask is in flight (disables the clarification re-submit). */
  busy: boolean
  /**
   * Whether this is the LATEST turn in the thread. A clarification card is a live,
   * actionable prompt ONLY while it is the latest turn; once the user has moved on
   * (asked, rephrased, or skipped) it renders as an inert historical note — this is
   * what stops an old clarification from lingering or re-firing its trigger (C26).
   */
  isLatest: boolean
}

/** A single conversation turn: question, then pending/answer/clarification/error. */
export function ConversationTurnView({
  turn,
  expanded,
  collapsible,
  onToggle,
  onResubmitClarification,
  busy,
  isLatest,
}: ConversationTurnViewProps) {
  return (
    <div className="space-y-2">
      {/* Question (blue) */}
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm bg-blue-600 px-3 py-2 text-sm text-white">
          {turn.question}
        </div>
      </div>

      {/* Body */}
      <div className="rounded-lg rounded-bl-sm border border-gray-200 bg-white px-3 py-2">
        {turn.status === 'pending' ? (
          <p className="inline-flex items-center gap-2 text-xs text-gray-500">
            <Spinner /> The agent is working on it…
          </p>
        ) : turn.status === 'error' ? (
          <p role="alert" className="text-sm text-red-600">
            {turn.error}
          </p>
        ) : turn.status === 'clarification' && turn.clarificationQuestion ? (
          <ClarificationTurn
            clarificationQuestion={turn.clarificationQuestion}
            onResubmit={onResubmitClarification}
            busy={busy}
            resolved={!isLatest}
          />
        ) : turn.answer ? (
          collapsible && !expanded ? (
            <CollapsedAnswer answer={turn.answer} onExpand={onToggle} />
          ) : (
            <AnswerView
              answer={turn.answer}
              collapsible={collapsible}
              onCollapse={collapsible ? onToggle : undefined}
              answeredAt={turn.answeredAt}
              durationMs={turn.durationMs}
            />
          )
        ) : null}
      </div>
    </div>
  )
}

/** Collapsed view (C32): a one-line answer preview with an expand affordance. */
function CollapsedAnswer({ answer, onExpand }: { answer: AskResponse; onExpand: () => void }) {
  const preview = previewText(answer.answer_markdown ?? '')
  return (
    <button
      type="button"
      onClick={onExpand}
      aria-expanded="false"
      className="flex w-full items-center gap-2 text-left"
    >
      <span aria-hidden="true" className="text-gray-400">
        ▸
      </span>
      <span className="min-w-0 flex-1 truncate text-xs text-gray-500">
        {preview || '(answer)'}
      </span>
      <span className="shrink-0 text-[10px] text-blue-600">expand</span>
    </button>
  )
}

function AnswerView({
  answer,
  collapsible,
  onCollapse,
  answeredAt,
  durationMs,
}: {
  answer: AskResponse
  collapsible: boolean
  onCollapse?: () => void
  /** Epoch ms the answer landed (live) or its persisted time (history). */
  answeredAt?: number
  /** Response time in ms, shown next to the timestamp when known. */
  durationMs?: number
}) {
  const markdown = answer.answer_markdown ?? ''
  const steps: AskStep[] = answer.steps ?? []
  // Local clock time for the "Asked at" prefix; omitted when no timestamp.
  const askedAt =
    answeredAt !== undefined ? new Date(answeredAt).toLocaleTimeString() : null
  const stepCount = steps.length
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {answer.is_best_effort && (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
              Best effort
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {collapsible && onCollapse && (
            <button
              type="button"
              onClick={onCollapse}
              aria-expanded="true"
              className="shrink-0 text-[11px] font-medium text-gray-400 hover:text-gray-700"
            >
              collapse
            </button>
          )}
        </div>
      </div>

      <Markdown>{markdown}</Markdown>

      {/* Inline ECharts charts captured during analysis (C4). */}
      {answer.charts && answer.charts.length > 0 && (
        <ChartRender charts={answer.charts} />
      )}

      {/* Datasets used disclosure */}
      {answer.datasets_used && answer.datasets_used.length > 0 && (
        <p className="mt-2 text-[11px] text-gray-400">
          Datasets used ({answer.datasets_used.length}): {answer.datasets_used.join(', ')}
        </p>
      )}

      {/* Meta: asked-at time + iterations + token counts */}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-gray-100 pt-2 text-[11px] text-gray-500">
        {askedAt && (
          <>
            <span>Asked at {askedAt}</span>
            <span aria-hidden="true">·</span>
          </>
        )}
        {durationMs !== undefined && (
          <>
            <span className="tabular-nums">took {formatDuration(durationMs)}</span>
            <span aria-hidden="true">·</span>
          </>
        )}
        <span className="tabular-nums">
          {answer.iteration_count ?? 0} iteration
          {(answer.iteration_count ?? 0) === 1 ? '' : 's'}
        </span>
        <span aria-hidden="true">·</span>
        <span className="tabular-nums">
          Tokens: {answer.tokens_input ?? 0} in / {answer.tokens_output ?? 0} out
        </span>
        {answer.status && (
          <>
            <span aria-hidden="true">·</span>
            <span>status: {answer.status}</span>
          </>
        )}
      </div>

      <StepsInspector steps={steps} />

      {/* Provenance: how many pandas execution steps backed this answer (C4).
          Zero steps ⇒ the agent answered from schema/metadata without running
          code; ≥1 ⇒ that many code steps ran. */}
      <p className="mt-2 text-[11px] text-gray-400">
        {stepCount === 0
          ? '0 code steps — answered from schema'
          : `${stepCount} code step${stepCount === 1 ? '' : 's'}`}
      </p>

      {answer.prompt_breakdown && Object.keys(answer.prompt_breakdown).length > 0 && (
        <PromptBreakdown
          breakdown={
            Object.fromEntries(
              Object.entries(answer.prompt_breakdown).map(([k, v]) => [
                k,
                typeof v === 'number' ? v : Number(v) || 0,
              ]),
            )
          }
        />
      )}
    </div>
  )
}

/** Human-readable response time: "850ms", "3.4s", or "1m 5s". */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}

/** First line / sentence of the answer, trimmed for a collapsed preview. */
function previewText(markdown: string): string {
  const flat = markdown
    .replace(/[#*`>_~|-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return flat.length > 120 ? `${flat.slice(0, 120)}…` : flat
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  )
}
