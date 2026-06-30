import { PromptBreakdown } from 'agent-frontend'

// Collapsible token breakdown shown under an answer. Renders collapsed by
// default (a static preview can't click it open), so the card shows the toggle
// with the "{in} in · {out} out" summary chip.
export const Collapsed = () => (
  <PromptBreakdown
    breakdown={{
      total_prompt: 9982,
      tokens_output: 333,
      system_overhead: 6001,
      memory: 2874,
      dataset_schemas: 890,
      action_history: 217,
      history: 0,
      dataset_notes: 0,
    }}
  />
)
