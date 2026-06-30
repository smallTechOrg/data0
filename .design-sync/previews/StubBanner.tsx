import { StubBanner } from 'agent-frontend'

// The offline-mode banner. Only renders content when provider === 'stub'
// (no API key set) — that's the state worth previewing.
export const StubMode = () => <StubBanner provider="stub" />
