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
    """

    question: str
    dataset_id: str | None = None
    dataset_ids: list[str] | None = None
    session_id: str | None = None
    skip_clarification: bool = False
