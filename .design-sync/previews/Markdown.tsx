import { Markdown } from 'agent-frontend'

// Renders an agent answer's markdown (headings, lists, GFM tables, code).
export const AnswerWithTable = () => (
  <Markdown>{`### Total revenue by region

The **North** region leads, driving **42%** of total revenue.

| Region | Revenue | Orders |
| ------ | ------: | -----: |
| North  | $2,100  | 30 |
| East   | $1,500  | 45 |
| South  | $800    | 20 |
| West   | $600    | 15 |

Key takeaways:

- North has the highest revenue but a *lower* order count than East.
- East has the most orders, suggesting a lower average order value.
- Computed with \`df.groupby("region")["sales"].sum()\`.
`}</Markdown>
)

export const ShortAnswer = () => (
  <Markdown>{`The average order value is **$48.20**, up **12%** from the prior period.`}</Markdown>
)
