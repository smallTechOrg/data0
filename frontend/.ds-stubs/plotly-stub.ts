// Design-sync stub for plotly.js-dist-min — keeps the heavy chart lib out of the
// synced bundle. ChartRender dynamic-imports this; in the design tool charts are
// not rendered (no live figure data), so a no-op API is sufficient.
const api = {
  newPlot: async () => {},
  purge: () => {},
  toImage: async () => '',
}
export default api
