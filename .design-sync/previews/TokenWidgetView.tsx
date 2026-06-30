import { TokenWidgetView } from 'agent-frontend'

// Header token/usage widget: shows the active provider, last-turn token cost,
// today's rolling usage against the context limit, and the loaded datasets.
export const Active = () => (
  <TokenWidgetView
    provider="gemini"
    lastTokens={{ input: 9982, output: 333 }}
    stats={{
      date: '2026-06-30',
      model: 'gemini-3.1-flash-lite',
      tokens_input: 74530,
      tokens_output: 2294,
      query_count: 4,
      context_limit: 1000000,
      last_prompt_tokens: 9982,
      last_tokens_input: 9982,
      last_tokens_output: 333,
    }}
    statsError={null}
    datasets={[
      { id: 'd1', filename: 'orders.csv', row_count: 99441, col_count: 8, format: 'csv', origin: 'uploaded' },
      { id: 'd2', filename: 'customers.csv', row_count: 3095, col_count: 4, format: 'csv', origin: 'uploaded' },
    ]}
    userPrice={null}
  />
)

// Cold start: no turn has run yet and today's stats failed to load, so the
// widget shows its error affordance instead of usage numbers.
export const StatsError = () => (
  <TokenWidgetView
    provider="anthropic"
    lastTokens={null}
    stats={null}
    statsError="Could not load today's usage stats."
    datasets={[
      { id: 'd1', filename: 'transactions.csv', row_count: 250000, col_count: 12, format: 'csv', origin: 'uploaded' },
    ]}
    userPrice={{ inputPerMillion: 3.0, outputPerMillion: 15.0 }}
  />
)
