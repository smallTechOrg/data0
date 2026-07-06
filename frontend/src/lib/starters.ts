/**
 * C37 (Phase 10) — session-start starter questions, pure logic.
 *
 * Backs the "Try asking:" chips ConversationCard shows on an EMPTY conversation:
 *  - `coerceStarterQuestions` turns an untrusted `GET /suggestions/starters`
 *    payload into at most 3 clean question strings.
 *  - `createStartersLoader` wraps the fetch in a once-per-mount memo, per the
 *    spec's stated assumption (spec/capabilities/suggested-questions.md): the
 *    FIRST call fetches; every later call — including concurrent ones — reuses
 *    the same promise, so a "New session" reset re-shows the cached chips
 *    without another LLM call and a page reload refetches naturally.
 *
 * Failure posture (spec/api.md): the endpoint never 5xxes, but the frontend is
 * equally defensive — any fetch error (e.g. a 404 before the backend slice
 * lands) resolves to `[]`, which the UI renders as NOTHING (no placeholder, no
 * spinner, no console noise). The failure is cached too: one attempt per mount.
 */

/** The spec caps starters at 3 questions (mirrors the backend `_MAX_SUGGESTIONS`). */
export const MAX_STARTERS = 3

/** Coerce an untrusted starters payload into at most 3 non-empty, trimmed questions. */
export function coerceStarterQuestions(payload: unknown): string[] {
  if (!payload || typeof payload !== 'object') return []
  const raw = (payload as { questions?: unknown }).questions
  if (!Array.isArray(raw)) return []
  const questions: string[] = []
  for (const item of raw) {
    if (questions.length >= MAX_STARTERS) break
    if (typeof item === 'string' && item.trim().length > 0) {
      questions.push(item.trim())
    }
  }
  return questions
}

/**
 * Memoize a starters fetch to exactly one attempt per loader instance.
 *
 * Returns a function that always resolves (never rejects) with the coerced
 * questions; errors and empty payloads resolve to `[]`. The single underlying
 * promise is shared by concurrent callers (React StrictMode's double-effect
 * fires one network request, not two).
 */
export function createStartersLoader(
  fetchStarters: () => Promise<unknown>,
): () => Promise<string[]> {
  let cached: Promise<string[]> | null = null
  return () => {
    if (!cached) {
      cached = (async () => {
        try {
          return coerceStarterQuestions(await fetchStarters())
        } catch {
          // Silent by design — the "Try asking:" block simply doesn't render.
          return []
        }
      })()
    }
    return cached
  }
}
