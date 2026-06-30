import { ConversationTurnView } from 'agent-frontend'

// Answered turn: a completed data-analysis question with rendered markdown
// (including a results table), the agent's step-by-step action trace with
// reasoning, token/prompt accounting, and suggested follow-up questions.
// Expanded and collapsible.
export const Answer = () => (
  <ConversationTurnView
    turn={{
      id: 't1',
      question: 'What is total revenue by region, and which region leads?',
      status: 'answer',
      answeredAt: 1751270000000,
      durationMs: 6700,
      answer: {
        type: 'answer',
        run_id: 'r1',
        answer_markdown: `### Revenue by region

The **North** region leads with **$2,100**.

| Region | Revenue |
| ------ | ------: |
| North | $2,100 |
| East | $1,500 |
| South | $800 |`,
        iteration_count: 2,
        tokens_input: 9982,
        tokens_output: 333,
        steps: [
          {
            action: 'df.columns.tolist()',
            result: "['region','sales']",
            is_error: false,
            reasoning: 'Inspect columns first.',
          },
          {
            action: "df.groupby('region')['sales'].sum().sort_values(ascending=False)",
            result: 'North 2100\nEast 1500\nSouth 800',
            is_error: false,
            reasoning: 'Aggregate sales per region and rank.',
          },
        ],
        suggested_questions: [
          'Break this down by month',
          'Which region grew fastest?',
        ],
        prompt_breakdown: {
          total_prompt: 9982,
          tokens_output: 333,
          system_overhead: 6001,
          memory: 2874,
          dataset_schemas: 890,
          action_history: 217,
          history: 0,
          dataset_notes: 0,
        },
      },
    }}
    expanded={true}
    collapsible={true}
    onToggle={() => {}}
    onResubmitClarification={() => {}}
    busy={false}
  />
)

// Clarification turn: the agent could not act on an ambiguous question and asked
// a follow-up before running. Shown expanded; not collapsible since there is no
// answer body to hide.
export const Clarification = () => (
  <ConversationTurnView
    turn={{
      id: 't2',
      question: 'Show me the breakdown',
      status: 'clarification',
      clarificationQuestion:
        'Breakdown of what — revenue, order count, or units? And by region or by month?',
      originalQuestion: 'Show me the breakdown',
    }}
    expanded={true}
    collapsible={false}
    onToggle={() => {}}
    onResubmitClarification={() => {}}
    busy={false}
  />
)
