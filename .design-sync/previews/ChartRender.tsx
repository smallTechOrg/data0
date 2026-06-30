import { ChartRender } from 'agent-frontend'

// ChartRender takes `charts: string[]` — each entry is a JSON-stringified ECharts
// `option` object, exactly what the agent emits via the sandbox `echart(...)` helper
// (right-side vertical legend, title top-centered, grid leaves room on the right).

const barOption = JSON.stringify({
  title: { text: 'Total revenue by region', left: 'center', top: 6 },
  tooltip: { trigger: 'axis' },
  legend: { type: 'scroll', orient: 'vertical', right: 8, top: 'middle' },
  grid: { left: 8, right: 120, top: 48, bottom: 24, containLabel: true },
  xAxis: { type: 'category', data: ['North', 'East', 'South', 'West'] },
  yAxis: { type: 'value', name: 'USD' },
  series: [
    { name: '2025', type: 'bar', data: [2100, 1500, 800, 600] },
    { name: '2024', type: 'bar', data: [1800, 1400, 900, 500] },
  ],
})

const lineOption = JSON.stringify({
  title: { text: 'Monthly orders trend', left: 'center', top: 6 },
  tooltip: { trigger: 'axis' },
  legend: { type: 'scroll', orient: 'vertical', right: 8, top: 'middle' },
  grid: { left: 8, right: 120, top: 48, bottom: 24, containLabel: true },
  xAxis: { type: 'category', data: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'] },
  yAxis: { type: 'value' },
  series: [{ name: 'orders', type: 'line', smooth: true, areaStyle: {}, data: [120, 200, 150, 80, 170, 210] }],
})

export const Bar = () => <ChartRender charts={[barOption]} />
export const Line = () => <ChartRender charts={[lineOption]} />
