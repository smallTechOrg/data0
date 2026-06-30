// Synthetic design-sync entry — re-exports the components to bundle into
// window.DAA.*. Not used by the Next app build. Scoped to standalone-renderable
// components: the original 7 presentational + the extracted *View primitives +
// the prop-driven panels (ERDiagramPanel, UploadCard, ChartRender).
export { StubBanner } from './src/components/StubBanner'
export { ProgressBar } from './src/components/analyse/ProgressBar'
export { SuggestionChips } from './src/components/analyse/SuggestionChips'
export { Markdown } from './src/components/analyse/Markdown'
export { ClarificationTurn } from './src/components/analyse/ClarificationTurn'
export { PromptBreakdown } from './src/components/analyse/PromptBreakdown'
export { StepsInspector } from './src/components/analyse/StepsInspector'
// Extracted presentational primitives (container/View split):
export { TokenWidgetView } from './src/components/analyse/TokenWidget'
export { MemoryModalView } from './src/components/analyse/MemoryModal'
export { SettingsPanelView } from './src/components/analyse/SettingsPanel'
export { CleanModalView } from './src/components/database/CleanModal'
export { SessionSidebarView } from './src/components/analyse/SessionSidebar'
export { TablesCardView } from './src/components/analyse/TablesCard'
export { TableDescriptionPanelView } from './src/components/database/TableDescriptionPanel'
export { ConversationTurnView } from './src/components/analyse/ConversationTurnView'
// Already prop-driven (no refactor needed):
export { ERDiagramPanel } from './src/components/database/ERDiagramPanel'
export { UploadCard } from './src/components/analyse/UploadCard'
// Charts — now ECharts-based (lightweight), a real synced primitive:
export { ChartRender } from './src/components/analyse/ChartRender'
