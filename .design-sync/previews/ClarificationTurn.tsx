import { ClarificationTurn } from 'agent-frontend'

// Amber pre-flight (C26) turn: the agent asks a clarifying question before it
// analyses. onResubmit re-sends the original question with skip_clarification.
export const Asking = () => (
  <ClarificationTurn
    clarificationQuestion={
      'Did you mean total revenue per region, or the average order value per region? Both are computable from this dataset.'
    }
    onResubmit={() => {}}
  />
)

export const Resubmitting = () => (
  <ClarificationTurn
    clarificationQuestion={'Which date column should I treat as the order date — created_at or shipped_at?'}
    onResubmit={() => {}}
    busy
  />
)
