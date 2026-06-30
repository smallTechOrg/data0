import { ProgressBar } from 'agent-frontend'

// Live agent-progress bar driven by GET /runs/current. The primary axis is how
// far the ReAct loop has progressed (iteration / max), plus the indeterminate
// pre-flight state.
export const Thinking = () => <ProgressBar label="Thinking…" iteration={3} max={12} />
export const NearlyDone = () => <ProgressBar label="Thinking…" iteration={10} max={12} />
export const Preflight = () => <ProgressBar label="Checking…" iteration={null} max={null} />
