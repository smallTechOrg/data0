'use client'

/**
 * Suggestion chips (Phase 3 — C22; label prop Phase 10 — C37).
 *
 * Renders a list of suggested questions as clickable chips. Clicking a chip
 * hands it to the parent via `onPick` — which drops it into the composer for
 * the user to edit or confirm (it does NOT auto-submit). Renders nothing when
 * there are no suggestions, so an empty list never leaves a dangling label.
 *
 * The optional `label` heading keeps the default "Follow-up suggestions" for
 * post-answer chips; C37 reuses the component with "Try asking:" for
 * session-start starters and a refine-oriented label on clarification turns.
 */
export function SuggestionChips({
  suggestions,
  onPick,
  disabled = false,
  label = 'Follow-up suggestions',
}: {
  suggestions: string[]
  onPick: (question: string) => void
  disabled?: boolean
  /** Heading shown above the chips (only when at least one chip renders). */
  label?: string
}) {
  const items = (suggestions ?? []).filter(s => s && s.trim().length > 0)
  if (items.length === 0) return null

  return (
    <div className="mt-3">
      <p className="mb-1.5 text-[11px] font-medium text-gray-500">{label}</p>
      <div className="flex flex-wrap gap-2">
        {items.map((s, i) => (
          <button
            key={`${i}-${s}`}
            type="button"
            disabled={disabled}
            onClick={() => onPick(s)}
            className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:border-blue-300 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

