import { SessionSidebarView } from 'agent-frontend'

// Session list sidebar: each row is a prior conversation (named or falling back
// to its first question), with the active session highlighted.
export const Sessions = () => (
  <SessionSidebarView
    sessions={[
      { id: 's1', name: 'Q3 revenue review', turn_count: 4, first_question: 'What is total revenue by region?' },
      { id: 's2', name: null, turn_count: 1, first_question: 'Show me the summary of customer orders' },
    ]}
    activeSessionId="s1"
    loading={false}
    error={null}
    busyId={null}
    bulkDeleting={false}
    clearingAll={false}
    onResume={() => {}}
    onNew={() => {}}
    onOpenMemory={() => {}}
    onRetry={() => {}}
    onRename={() => {}}
    onDelete={() => {}}
    onClearAll={() => {}}
    onBulkDelete={() => {}}
  />
)

// Empty + failed load: no sessions yet and the list fetch errored, exercising
// the sidebar's error/retry affordance.
export const LoadError = () => (
  <SessionSidebarView
    sessions={[]}
    activeSessionId={null}
    loading={false}
    error="Failed to load sessions."
    busyId={null}
    bulkDeleting={false}
    clearingAll={false}
    onResume={() => {}}
    onNew={() => {}}
    onOpenMemory={() => {}}
    onRetry={() => {}}
    onRename={() => {}}
    onDelete={() => {}}
    onClearAll={() => {}}
    onBulkDelete={() => {}}
  />
)
