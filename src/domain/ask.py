from pydantic import BaseModel


class AskRequest(BaseModel):
    """Request body for `POST /ask`.

    - `dataset_id` / `dataset_ids` — accepted for API compatibility but IGNORED;
      dataset selection is agent-driven since Phase 6 (the agent picks from the
      full catalog autonomously).
    - `session_id` — resumes an existing conversation session (20-turn cap);
      omit to start a new session.
    - `skip_clarification` — suppresses the C26 pre-flight clarification check
      (first turn only).
    - `fast_mode` (C35) — a per-request latency toggle, default `false`. When
      `true`: tightens `max_iterations` to `5` for this request only (overriding
      the settings/DB value); skips the C26 clarification check outright
      (regardless of first-turn status); skips `generate_suggestions`. Never
      persisted; never affects model/provider selection. See
      spec/capabilities/fast-mode.md.
    """

    question: str
    dataset_id: str | None = None
    dataset_ids: list[str] | None = None
    session_id: str | None = None
    skip_clarification: bool = False
    fast_mode: bool = False
