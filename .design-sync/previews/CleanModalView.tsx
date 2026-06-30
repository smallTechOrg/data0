import { CleanModalView } from 'agent-frontend'

// Data-cleaning preview: the user describes a transform in natural language, the
// agent generates pandas code and shows before/after row counts and sample rows.
export const Preview = () => (
  <CleanModalView
    open={true}
    filename="orders.csv"
    instruction="Drop rows where total is null and trim whitespace in the region column"
    previewing={false}
    applying={false}
    error={null}
    preview={{
      code:
        "df = df.dropna(subset=['total'])\ndf['region'] = df['region'].str.strip()",
      before_row_count: 99441,
      after_row_count: 98220,
      before_col_count: 8,
      after_col_count: 8,
      before_preview: {
        columns: ['region', 'total'],
        rows: [
          ['North ', 1200],
          [null, 800],
        ],
      },
      after_preview: {
        columns: ['region', 'total'],
        rows: [
          ['North', 1200],
          ['East', 1500],
        ],
      },
    }}
    onClose={() => {}}
    onInstructionChange={() => {}}
    onPreview={() => {}}
    onApply={() => {}}
  />
)

// Empty state: modal just opened for a fresh dataset, no instruction typed yet
// and no preview generated.
export const Empty = () => (
  <CleanModalView
    open={true}
    filename="customers.csv"
    instruction=""
    preview={null}
    previewing={false}
    applying={false}
    error={null}
    onClose={() => {}}
    onInstructionChange={() => {}}
    onPreview={() => {}}
    onApply={() => {}}
  />
)
