// Synthetic design-sync entry — re-exports the presentational components so the
// converter can bundle them into window.DAA.*. Not used by the Next app build.
// Scoped to standalone-renderable components (no backend fetch on mount).
export { StubBanner } from './src/components/StubBanner'
export { ProgressBar } from './src/components/analyse/ProgressBar'
export { SuggestionChips } from './src/components/analyse/SuggestionChips'
export { Markdown } from './src/components/analyse/Markdown'
export { ClarificationTurn } from './src/components/analyse/ClarificationTurn'
export { PromptBreakdown } from './src/components/analyse/PromptBreakdown'
export { StepsInspector } from './src/components/analyse/StepsInspector'
