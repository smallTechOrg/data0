'use client'

import { useState } from 'react'

/**
 * PromptBreakdown (C29) — collapsible per-component prompt token breakdown.
 *
 * Shows `total_prompt` as a summary at the top, then each named component as a
 * labelled row with a proportional bar. Collapsed by default; a chevron toggles
 * it open. Consistent with the StepsInspector collapsible pattern.
 *
 * Only rendered when the parent passes a non-empty breakdown object containing
 * at least one key.
 */

/**
 * Human-readable label overrides for known breakdown keys (spec/capabilities/
 * context-window-display.md). Unknown keys fall back to a title-cased version
 * of the snake_case key name.
 */
const LABEL_MAP: Record<string, string> = {
  total_prompt: 'Input total',
  dataset_schemas: 'Dataset schemas',
  history: 'Conversation history',
  dataset_notes: 'Dataset notes',
  memory: 'Memory',
  action_history: 'Action history',
  system_overhead: 'System overhead',
}

function humanLabel(key: string): string {
  return (
    LABEL_MAP[key] ??
    key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase())
  )
}

/** Bar colour: use blue-400 for regular components; a slightly darker shade for total. */
function barClass(isTotal: boolean): string {
  return isTotal ? 'bg-blue-500' : 'bg-blue-300'
}

export function PromptBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
  const [open, setOpen] = useState(false)

  // Extract total_prompt for proportional bars. Fall back to summing all
  // component keys (excluding total_prompt AND tokens_output) if total_prompt
  // is absent so bars are still meaningful.
  const total =
    breakdown.total_prompt ??
    Object.entries(breakdown)
      .filter(([k]) => k !== 'total_prompt' && k !== 'tokens_output')
      .reduce((a, [, b]) => a + b, 0)

  // Separate total_prompt and tokens_output from the component rows; the six
  // input components sum to total_prompt and are shown as proportional bars.
  // Output is rendered separately below the list. Sort components by value desc.
  const componentEntries = Object.entries(breakdown)
    .filter(([k]) => k !== 'total_prompt' && k !== 'tokens_output')
    .sort(([, a], [, b]) => b - a)

  const hasComponents = componentEntries.length > 0

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-700 hover:text-gray-900"
      >
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
        Token breakdown
        {total > 0 && (
          <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-500 tabular-nums">
            {total.toLocaleString()} in · {(breakdown.tokens_output ?? 0).toLocaleString()} out
          </span>
        )}
      </button>

      {open && (
        <div className="mt-2 rounded-md border border-gray-200 bg-gray-50 p-3">
          {/* Caption: clarifies this widget shows the composition of the most recent
              prompt, distinct from cumulative query tokens in the Token usage panel. */}
          <p className="mb-2 text-[11px] text-gray-400">
            Input tokens for this query, broken down by component (sums to Last
            query In). Output is the model&apos;s response.
          </p>
          {/* Summary row: total_prompt */}
          <div className="mb-2 flex items-center justify-between gap-2 text-[11px]">
            <span className="font-semibold text-gray-700">
              {humanLabel('total_prompt')}
            </span>
            <span className="font-semibold tabular-nums text-gray-700">
              {total.toLocaleString()}
            </span>
          </div>

          {/* Bar for the total */}
          {total > 0 && (
            <div
              role="presentation"
              className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-gray-200"
            >
              <div className={`h-full w-full ${barClass(true)}`} />
            </div>
          )}

          {/* Per-component rows */}
          {hasComponents && (
            <ol className="space-y-2" aria-label="Prompt components">
              {componentEntries.map(([key, value]) => {
                const pct =
                  total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 0
                return (
                  <li key={key}>
                    <div className="mb-0.5 flex items-center justify-between gap-2 text-[11px]">
                      <span className="text-gray-600">{humanLabel(key)}</span>
                      <span className="tabular-nums text-gray-600">
                        {value.toLocaleString()}
                        {total > 0 && (
                          <span className="ml-1 text-gray-400">({pct}%)</span>
                        )}
                      </span>
                    </div>
                    <div
                      role="progressbar"
                      aria-label={`${humanLabel(key)} token share`}
                      aria-valuenow={pct}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      className="h-1 w-full overflow-hidden rounded-full bg-gray-200"
                    >
                      <div
                        className={`h-full transition-all ${barClass(false)}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </li>
                )
              })}
            </ol>
          )}

          {/* Output row: the model's response tokens, distinct from the input
              partition above — no proportional bar, shown under a thin divider. */}
          {(breakdown.tokens_output ?? 0) > 0 && (
            <div className="mt-3 flex items-center justify-between gap-2 border-t border-gray-200 pt-2 text-[11px]">
              <span className="font-medium text-gray-600">Output (response)</span>
              <span className="font-medium tabular-nums text-gray-600">
                {breakdown.tokens_output.toLocaleString()}
              </span>
            </div>
          )}

          {!hasComponents && total === 0 && (
            <p className="text-[11px] text-gray-400">No breakdown data available.</p>
          )}
        </div>
      )}
    </div>
  )
}


