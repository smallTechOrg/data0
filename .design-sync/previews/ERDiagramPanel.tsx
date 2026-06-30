import { ERDiagramPanel } from 'agent-frontend'

// Schema / ER-diagram panel: three uploaded datasets whose shared *_id columns
// produce inferred foreign-key edges (orders.customer_id → customers,
// orders → products via the products table). One table is selected (orders) and
// the sibling description panel is collapsed.
export const Diagram = () => (
  <ERDiagramPanel
    datasets={[
      {
        id: 'd1',
        filename: 'orders.csv',
        row_count: 99441,
        col_count: 4,
        format: 'csv',
        origin: 'uploaded',
        columns: ['order_id', 'customer_id', 'region', 'total'],
      },
      {
        id: 'd2',
        filename: 'customers.csv',
        row_count: 3095,
        col_count: 3,
        format: 'csv',
        origin: 'uploaded',
        columns: ['customer_id', 'name', 'city'],
      },
      {
        id: 'd3',
        filename: 'products.csv',
        row_count: 71,
        col_count: 2,
        format: 'csv',
        origin: 'uploaded',
        columns: ['product_id', 'category'],
      },
    ]}
    selectedId="d1"
    onSelect={() => {}}
    detailsOpen={false}
    onToggleDetails={() => {}}
  />
)
