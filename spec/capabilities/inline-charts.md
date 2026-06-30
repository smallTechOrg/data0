# Capability: Inline ECharts Charts (C4)

## What It Does
Captures any chart the agent creates during analysis — via the `echart(...)` sandbox helper — and returns it as an ECharts `option` JSON object for inline rendering.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| chart(s) | ECharts `option` dict built by `echart(...)` | execute_action sandbox | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| charts | list[JSON] | `AgentState.charts` → answer |

## External Calls
None (charts rendered client-side with ECharts).

## Business Rules
- The model calls `echart(kind, df, *, x, y, series, title, option, **opts)` in the sandbox. It builds a sensible ECharts `option` dict (`{title, tooltip, xAxis, yAxis, series, legend, grid, ...}`) for `kind ∈ {bar, line, scatter, pie, heatmap}`, or accepts a full raw `option=<dict>` (must contain a `series` key) as an escape hatch. It REGISTERS the option into a per-run accumulator and returns the dict.
- `execute_action` reads that accumulator, `json.dumps`-es each option, and appends the strings to `state["charts"]` (the `query_runs.charts_json` shape — an array of JSON strings — is unchanged; only the content is now an ECharts option rather than a Plotly figure).
- Chart building is defensive: bad input raises a clear `ValueError` the eval loop recovers from (recorded as a step error), and never crashes the run.
- `finalize` carries the captured chart JSON on the answer's `charts`; the UI renders them inline (ECharts).
- A chart-capture/serialisation failure is non-fatal (step error, run continues).

## Chart Guardrail (deterministic)

When the user's question explicitly requests a chart (`"plot"`, `"chart"`, `"graph"`, `"visuali[sz]e"`, `"show me"` etc. — regex in `_wants_chart`), the graph enforces production of at least one chart before finalizing:

- `setup` sets `wants_chart = True` in `AgentState`.
- `after_plan`: if the model emits a `FINAL ANSWER:` with `wants_chart=True` but no charts captured yet, AND `chart_force_count < 2`, the edge returns `"plan_action"` (self-loop) instead of `"finalize"`, increments `chart_force_count`, and injects a `## A chart is REQUIRED` reminder into the next prompt.
- Cap: after 2 rejections (`chart_force_count >= 2`) the guard gives up and routes to `finalize` normally — the run never loops forever.

## Success Criteria
- [ ] A question that asks for a distribution/plot yields at least one ECharts `option` JSON (with a `series` key) in the response.
- [ ] The UI renders the chart inline within the answer turn.
