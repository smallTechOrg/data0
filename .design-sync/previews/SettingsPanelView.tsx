import { SettingsPanelView } from 'agent-frontend'

// Agent settings: pick the LLM model, cap the agent's iteration budget, and set
// per-million token pricing used to cost each data-analysis run.
export const Settings = () => (
  <SettingsPanelView
    open={true}
    form={{
      llm_model: 'gemini-3.1-flash-lite',
      max_iterations: '12',
      price_input_per_million: '0.25',
      price_output_per_million: '1.50',
    }}
    models={[
      {
        value: 'gemini-3.1-flash-lite',
        label: 'Gemini 3.1 Flash Lite (default)',
        input: 0.25,
        output: 1.5,
      },
      {
        value: 'gemini-2.5-pro',
        label: 'Gemini 2.5 Pro',
        input: 1.25,
        output: 10,
      },
      {
        value: 'claude-haiku-4-5-20251001',
        label: 'Claude Haiku 4.5',
        input: 0.8,
        output: 4,
      },
    ]}
    saving={false}
    error={null}
    saved={false}
    priceAutoFilled={false}
    onClose={() => {}}
    onModelChange={() => {}}
    onMaxIterationsChange={() => {}}
    onPriceChange={() => () => {}}
    onSave={() => {}}
  />
)
