'use client'

/**
 * Fast Mode toggle (C35) — a visible, per-query switch in the Analyse composer.
 * Default OFF. Deliberately NOT a Settings-page global: model/provider selection
 * stays Settings-owned, and Fast Mode is a low-friction, turn-by-turn trade-off
 * the user opts into right next to the question (spec/capabilities/fast-mode.md,
 * "Resolved Decisions"). State lives in the parent (ConversationCard) and is
 * never persisted — it resets each composer session, no cross-reload requirement.
 *
 * Sized as a standalone control (not the small-chip family used elsewhere in
 * this file, e.g. "Collapse all" / "Expand all") so it reads as a prominent,
 * deliberate per-query switch rather than a faint label. ON state borrows the
 * same soft-accent chip look used for "Best effort" (bg-blue-100/text-blue-700)
 * so it reads as an active state, theme-aware via the globals.css remap — no
 * hardcoded colors.
 */
export function FastModeToggle({
  enabled,
  onChange,
  disabled,
}: {
  enabled: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
      disabled={disabled}
      aria-pressed={enabled}
      title="Fast Mode: fewer iterations, no clarification, shorter answers — trades a little depth for speed"
      className={
        enabled
          ? 'rounded-md border-2 border-blue-300 bg-blue-100 px-3 py-1.5 text-sm font-semibold text-blue-700 shadow-sm hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60'
          : 'rounded-md border-2 border-gray-300 px-3 py-1.5 text-sm font-semibold text-gray-600 hover:bg-gray-100 hover:text-gray-800 disabled:cursor-not-allowed disabled:opacity-60'
      }
    >
      ⚡ Fast Mode{enabled ? ': On' : ''}
    </button>
  )
}
