"""Pre-flight one-shot LLM call run BEFORE the ReAct graph.

Per `spec/agent.md` -> "## Pre-flight". Dataset SELECTION is now AGENT-DRIVEN (the
agent picks from a catalog of all datasets inside the graph), so the only pre-flight
left is the C26 clarification check. It runs in `runner.run_agent` on the first turn
of a conversation (`run_clarification=True`) and is skipped on follow-ups.

`check_clarification` (C26 + C37): an ambiguous question -> ONE clarifying question
plus up to 3 refined candidate questions (`ClarificationResult`), all from the SAME
single call (the run short-circuits, no graph). Otherwise `proceed` -> `None`.

It goes through `LLMClient.call_model` (never a provider SDK) and is FAIL-OPEN: an
LLM error never blocks the user — clarification returns `None` (proceed). A reply
that ignores the JSON grammar degrades to the pre-C37 behavior (the whole trimmed
reply is the clarifying question, candidates `[]`) — parsing never blocks or
downgrades the clarification itself. Contract:
`spec/capabilities/suggested-questions.md`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

from llm.client import LLMClient
from observability.events import get_logger

logger = get_logger("graph.preflight")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_CLARIFY_PROMPT_PATH = _PROMPTS_DIR / "clarify.md"

# Node tag the stub provider branches on (must match stub.py EXACTLY).
_CLARIFY_TAG = "<node:clarify>"

# C37: at most 3 refined candidate questions ride the clarification.
_MAX_CLARIFY_SUGGESTIONS = 3


class ClarificationResult(NamedTuple):
    """The C26 clarification + its C37 refined candidates (one LLM call).

    NamedTuple per the repo's `LLMResponse` convention. `suggestions` is `[]`
    whenever the model offered none or its reply fell back to plain-text parsing.
    """

    question: str
    suggestions: list[str]


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _coerce_suggestions(value: object) -> list[str]:
    """Coerce the reply's `suggestions` to <=3 non-empty strings; [] on anything else."""
    if not isinstance(value, list):
        return []
    out = [str(x).strip() for x in value if str(x).strip()]
    return out[:_MAX_CLARIFY_SUGGESTIONS]


def _strip_fence(text: str) -> str:
    """Strip an optional wrapping code fence (same tolerance as `_coerce_string_list`)."""
    if text.startswith("```"):
        text = text.strip("`")
        text = re.sub(r"^[a-zA-Z]*\n", "", text, count=1).strip()
    return text


def _parse_clarification_reply(reply: str) -> ClarificationResult:
    """Parse the extended C37 reply -> `ClarificationResult` (never raises).

    Fence-strip, extract the FIRST `{...}` span, `json.loads` it; a dict with a
    non-empty string `question` wins (with `suggestions` coerced to <=3 strings).
    ANY parse failure (no span, bad JSON, missing/empty `question`) falls back to
    the pre-C37 behavior byte-for-byte: the whole trimmed reply — stripped of
    wrapping backticks/quotes exactly as before — is the clarifying question,
    with candidates `[]`.
    """
    stripped = _strip_fence(reply.strip())
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
            if isinstance(payload, dict):
                question = payload.get("question")
                if isinstance(question, str) and question.strip():
                    return ClarificationResult(
                        question.strip(),
                        _coerce_suggestions(payload.get("suggestions")),
                    )
        except Exception:  # noqa: BLE001 — fall back to plain-text parsing
            pass

    # Fallback: today's exact behavior — strip wrapping quotes/backticks the model
    # may add around a plain-text question; no candidates.
    return ClarificationResult(reply.strip().strip("`").strip('"').strip(), [])


def check_clarification(question: str, schemas: str) -> ClarificationResult | None:
    """C26 (+C37) pre-flight clarification check — ONE LLM call.

    Returns `None` to PROCEED (question is answerable as-is), or a
    `ClarificationResult(question, suggestions)` when the model judges the
    question ambiguous: the clarifying question plus up to 3 refined candidate
    questions from the SAME single call (no extra roundtrip).

    Fail-open: any LLM error returns `None` (never block the user). The model is
    told to reply `proceed` or one JSON object; we treat a reply that starts
    with / contains "proceed" as proceed, otherwise parse the JSON object (any
    parse failure -> the whole trimmed reply is the question, candidates `[]`).
    """
    try:
        system = _load_prompt(_CLARIFY_PROMPT_PATH)
        prompt = (
            f"{_CLARIFY_TAG}\n\n"
            f"## Question\n{question}\n\n"
            f"## Available datasets\n{schemas}\n\n"
            "Reply with exactly `proceed` if answerable, otherwise ONE JSON "
            'object {"question": ..., "suggestions": [...]} as instructed.'
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

    result = _parse_clarification_reply(reply)
    logger.info("clarification_parsed", suggestions=len(result.suggestions))
    return result
