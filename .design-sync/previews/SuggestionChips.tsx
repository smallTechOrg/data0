import { SuggestionChips } from 'agent-frontend'

// Follow-up suggestion chips shown under an answer. onPick drops the chosen
// question into the composer (no-op here).
export const Suggestions = () => (
  <SuggestionChips
    suggestions={[
      'Break this down by region',
      'Which month had the highest revenue?',
      'Show the trend over time as a chart',
    ]}
    onPick={() => {}}
  />
)

export const Disabled = () => (
  <SuggestionChips
    suggestions={['Compare to last quarter', 'Filter to top 10 customers']}
    onPick={() => {}}
    disabled
  />
)
