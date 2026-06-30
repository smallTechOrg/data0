import { ChartRender } from 'agent-frontend'

// ChartRender takes `charts: string[]` — each entry is a JSON-stringified ECharts
// `option` object, exactly what the agent emits via the sandbox `echart(...)` helper.

const barOption = JSON.stringify({
  title: { text: 'Total revenue by region' },
  tooltip: { trigger: 'axis' },
  legend: { top: 0 },
  grid: { left: 60, right: 24, top: 48, bottom: 40 },
  xAxis: { type: 'category', data: ['North', 'East', 'South', 'West'] },
  yAxis: { type: 'value', name: 'USD' },
  series: [
    { name: '2025', type: 'bar', data: [2100, 1500, 800, 600] },
    { name: '2024', type: 'bar', data: [1800, 1400, 900, 500] },
  ],
})

const lineOption = JSON.stringify({
  title: { text: 'Monthly orders trend' },
  tooltip: { trigger: 'axis' },
  legend: { top: 0 },
  grid: { left: 50, right: 24, top: 48, bottom: 40 },
  xAxis: { type: 'category', data: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'] },
  yAxis: { type: 'value' },
  series: [{ name: 'orders', type: 'line', smooth: true, areaStyle: {}, data: [120, 200, 150, 80, 170, 210] }],
})

export const Bar = () => <ChartRender charts={[barOption]} />
export const Line = () => <ChartRender charts={[lineOption]} />
