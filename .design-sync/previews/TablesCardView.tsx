import { TablesCardView } from 'agent-frontend'

// Datasets card: lists uploaded and derived tables with row/col counts, one row
// selected, and per-dataset column expansion collapsed.
export const Tables = () => (
  <TablesCardView
    datasets={[
      { id: 'd1', filename: 'orders.csv', row_count: 99441, col_count: 8, format: 'csv', origin: 'uploaded' },
      { id: 'd2', filename: 'customers.csv', row_count: 3095, col_count: 4, format: 'csv', origin: 'uploaded' },
      { id: 'd3', filename: 'orders_cleaned.csv', row_count: 98220, col_count: 8, format: 'csv', origin: 'derived', stale: false },
    ]}
    loading={false}
    error={null}
    selectedDatasetIds={['d1']}
    colsById={{}}
    deletingBulk={false}
    rederivingId={null}
    onRefresh={() => {}}
    onToggleSelect={() => {}}
    onSelectAll={() => {}}
    onClearSelection={() => {}}
    onDeleteSelected={() => {}}
    onToggleCols={() => {}}
    onClean={() => {}}
    onReDerive={() => {}}
  />
)

// Expanded columns + stale derived table: one table's schema is loaded inline
// and a derived dataset is flagged stale (its source changed), surfacing the
// re-derive affordance.
export const ExpandedAndStale = () => (
  <TablesCardView
    datasets={[
      { id: 'd1', filename: 'orders.csv', row_count: 99441, col_count: 8, format: 'csv', origin: 'uploaded' },
      { id: 'd3', filename: 'orders_cleaned.csv', row_count: 98220, col_count: 8, format: 'csv', origin: 'derived', stale: true },
    ]}
    loading={false}
    error={null}
    selectedDatasetIds={[]}
    colsById={{
      d1: {
        loading: false,
        error: null,
        columns: [
          { name: 'order_id', dtype: 'int64' },
          { name: 'customer_id', dtype: 'int64' },
          { name: 'order_date', dtype: 'datetime64[ns]' },
          { name: 'region', dtype: 'object' },
          { name: 'amount', dtype: 'float64' },
        ],
      },
    }}
    deletingBulk={false}
    rederivingId="d3"
    onRefresh={() => {}}
    onToggleSelect={() => {}}
    onSelectAll={() => {}}
    onClearSelection={() => {}}
    onDeleteSelected={() => {}}
    onToggleCols={() => {}}
    onClean={() => {}}
    onReDerive={() => {}}
  />
)
