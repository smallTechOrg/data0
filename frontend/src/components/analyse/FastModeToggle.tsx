'use client'

/**
 * Fast Mode toggle (C35) — a visible, per-query switch in the Analyse composer.
 * Default OFF. Deliberately NOT a Settings-page global: model/provider selection
 * stays Settings-owned, and Fast Mode is a low-friction, turn-by-turn trade-off
 * the user opts into right next to the question (spec/capabilities/fast-mode.md,
 * "Resolved Decisions"). State lives in the parent (ConversationCard) and is
 * never persisted — it resets each composer session, no cross-reload requirement.
 *
 * Visual language matches the existing small-chip family used elsewhere in this
 * file (e.g. "Collapse all" / "Expand all"): a bordered rounded chip, not a new
 * style. ON state borrows the same soft-accent chip look used for "Best effort"
 * (bg-blue-100/text-blue-700) so it reads as an active state, theme-aware via
 * the globals.css remap — no hardcoded colors.
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
          ? 'rounded border border-blue-300 bg-blue-100 px-1.5 py-0.5 text-[11px] font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60'
          : 'rounded border border-gray-300 px-1.5 py-0.5 text-[11px] font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-60'
      }
    >
      ⚡ Fast Mode{enabled ? ': On' : ''}
    </button>
  )
}
