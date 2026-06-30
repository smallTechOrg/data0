import { StepsInspector } from 'agent-frontend'

// Collapsible ReAct step trace (each step = reasoning + pandas action + result).
// Renders collapsed by default (a static preview can't click it open), so the
// card shows the "Steps inspector N" toggle.
export const Steps = () => (
  <StepsInspector
    steps={[
      {
        action: 'df.columns.tolist()',
        result: "['region', 'sales', 'units']",
        is_error: false,
        reasoning: 'First inspect the columns so I know the exact field names.',
      },
      {
        action: 'df.groupby("region")["sales"].sum().sort_values(ascending=False)',
        result: 'region\nNorth    2100\nEast     1500\nSouth     800\nWest      600',
        is_error: false,
        reasoning: 'Aggregate sales per region and rank to find the leader.',
      },
    ]}
  />
)
