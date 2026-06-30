import { TableDescriptionPanelView } from 'agent-frontend'

// Table description panel: full detail for one selected dataset — schema with
// dtypes, a sampled data preview, inferred primary/foreign keys, derivation
// context, and auto-generated analysis notes (status "done"). Code view and the
// clean/delete affordances are idle.
export const Detail = () => (
  <TableDescriptionPanelView
    datasetId="d1"
    detail={{
      id: 'd1',
      filename: 'orders.csv',
      row_count: 99441,
      col_count: 4,
      format: 'csv',
      origin: 'uploaded',
      columns_schema: [
        { name: 'order_id', dtype: 'int64' },
        { name: 'customer_id', dtype: 'int64' },
        { name: 'region', dtype: 'object' },
        { name: 'total', dtype: 'float64' },
      ],
      context: 'Each row is one order. total is in USD. customer_id joins customers.csv.',
      derivation_code: null,
      auto_notes_status: 'done',
      context_facts: [
        'total is USD',
        'one row per order',
        'joins customers on customer_id',
      ],
    }}
    preview={{
      columns: ['order_id', 'customer_id', 'region', 'total'],
      rows: [
        [1, 101, 'North', 1200.0],
        [2, 102, 'East', 1500.0],
        [3, 101, 'South', 800.0],
      ],
    }}
    loading={false}
    error={null}
    keys={{
      pk: ['order_id'],
      fk: [{ column: 'customer_id', references: 'customers.csv' }],
    }}
    pkSet={new Set(['order_id'])}
    fkMap={new Map([['customer_id', 'customers.csv']])}
    allDatasets={[]}
    notes="Each row is one order. total is in USD."
    savingNotes={false}
    savedNotes={false}
    notesStatus="done"
    showCode={false}
    cleanOpen={false}
    confirmDelete={false}
    busy={null}
    onCollapse={() => {}}
    onToggleCode={() => {}}
    onRetry={() => {}}
    onNotesChange={() => {}}
    onGenerateNotes={() => {}}
    onReDerive={() => {}}
    onOpenClean={() => {}}
    onCloseClean={() => {}}
    onCleanApplied={() => {}}
    onRequestDelete={() => {}}
    onCancelDelete={() => {}}
    onConfirmDelete={() => {}}
  />
)
