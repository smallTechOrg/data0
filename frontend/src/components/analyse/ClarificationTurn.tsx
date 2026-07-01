'use client'

/**
 * Clarification turn body (Phase 3 — C26).
 *
 * When POST /ask returns `type:"clarification"`, the agent is asking the user a
 * clarifying question before it analyses. This renders in AMBER, clearly framed
 * as "the agent is asking you" (not an error), with the clarification question
 * and a "Re-submit anyway" control that re-sends the SAME original question with
 * `skip_clarification: true` (in the same session). A "Refine question" hint
 * points the user at the composer if they would rather rephrase.
 */
export function ClarificationTurn({
  clarificationQuestion,
  onResubmit,
  busy = false,
  resolved = false,
}: {
  clarificationQuestion: string
  onResubmit: () => void
  busy?: boolean
  /** A resolved clarification is one the user has already moved past (it is no
   *  longer the latest turn): render it as an inert historical note with NO action
   *  button, so an old card can neither linger as a live prompt nor re-fire the
   *  original question when clicked later (C26). */
  resolved?: boolean
}) {
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <span aria-hidden="true" className="text-amber-600">
          ?
        </span>
        <span className="text-xs font-semibold text-amber-800">
          The agent needs clarification
        </span>
      </div>
      <p className="text-sm text-amber-900">{clarificationQuestion}</p>
      {resolved && (
        <p className="mt-2 text-[11px] font-medium text-amber-700">✓ Resolved — you continued below.</p>
      )}
      {!resolved && (
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onResubmit}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-white px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy && (
            <span
              aria-hidden="true"
              className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
            />
          )}
          Answer anyway (skip clarification)
        </button>
        <span className="text-[11px] text-amber-700">
          …or rephrase your question in the box below.
        </span>
      </div>
      )}
    </div>
  )
}

