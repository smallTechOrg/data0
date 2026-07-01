"""Pre-flight one-shot LLM call run BEFORE the ReAct graph.

Per `spec/agent.md` -> "## Pre-flight". Dataset SELECTION is now AGENT-DRIVEN (the
agent picks from a catalog of all datasets inside the graph), so the only pre-flight
left is the C26 clarification check. It runs in `runner.run_agent` on the first turn
of a conversation (`run_clarification=True`) and is skipped on follow-ups.

`check_clarification` (C26): an ambiguous question -> a single clarifying question
(the run short-circuits, no graph). Otherwise `proceed` -> `None`.

It goes through `LLMClient.call_model` (never a provider SDK) and is FAIL-OPEN: an
LLM error never blocks the user — clarification returns `None` (proceed).
"""
from __future__ import annotations

from pathlib import Path

from llm.client import LLMClient
from observability.events import get_logger

logger = get_logger("graph.preflight")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_CLARIFY_PROMPT_PATH = _PROMPTS_DIR / "clarify.md"

# Node tag the stub provider branches on (must match stub.py EXACTLY).
_CLARIFY_TAG = "<node:clarify>"


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def check_clarification(question: str, schemas: str) -> str | None:
    """C26: pre-flight clarification check.

    Returns `None` to PROCEED (question is answerable as-is), or a single
    clarifying question string when the model judges the question ambiguous.

    Fail-open: any LLM error returns `None` (never block the user). The model is
    told to reply `proceed` or one question; we treat a reply that starts with /
    contains "proceed" as proceed, otherwise the trimmed reply is the question.
    """
    try:
        system = _load_prompt(_CLARIFY_PROMPT_PATH)
        prompt = (
            f"{_CLARIFY_TAG}\n\n"
            f"## Question\n{question}\n\n"
            f"## Available datasets\n{schemas}\n\n"
            "Reply with exactly `proceed` if answerable, otherwise ONE short "
            "clarifying question."
        )
        reply = (LLMClient().call_model(prompt, system=system) or "").strip()
    except Exception as exc:  # noqa: BLE001 — fail-open, never block the user
        logger.warning("clarification_failed_proceeding", error=str(exc))
        return None

    if not reply:
        return None

    normalized = reply.lower().lstrip("`\"' ")
    if normalized.startswith("proceed") or "proceed" in normalized[:16]:
        return None

    # Strip wrapping quotes/backticks the model may add around the question.
    return reply.strip().strip("`").strip('"').strip()
