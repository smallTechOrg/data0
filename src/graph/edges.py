"""Conditional-edge routers for the ReAct graph.

Mirrors the table in `spec/agent.md` -> "## Graph / Flow Topology". Each function
returns the name of the next node; the graph maps those names to targets in
`agent.py`.
"""
from __future__ import annotations

from graph.cancellation import is_cancelled
from graph.state import AgentState

# 3 consecutive execution errors force a wrap-up (kept in sync with nodes.py).
_MAX_CONSECUTIVE_ERRORS = 3
_FINAL_MARKER = "final answer:"


def after_setup(state: AgentState) -> str:
    """setup -> handle_error on fatal load error, else plan_action."""
    if state.get("error"):
        return "handle_error"
    return "plan_action"


def after_plan(state: AgentState) -> str:
    """plan_action -> handle_error / force_finalize (cancelled) / finalize / execute_action."""
    if state.get("error"):
        return "handle_error"
    # User pressed Stop: wrap up now instead of running the planned action.
    if is_cancelled(state.get("run_id", "")):
        return "force_finalize"
    llm_response = (state.get("llm_response") or "").lower()
    is_final = _FINAL_MARKER in llm_response
    # Chart guardrail: the user explicitly asked for a chart but the model tried to
    # finalize without producing one. Loop back to plan_action ONCE more to force an
    # echart(...). `chart_force_count` (incremented in plan_action on each such
    # rejected finalize) caps the retries: once it reaches 2 we fall through to the
    # normal finalize, guaranteeing termination even if the model never charts (or
    # in stub mode, which never charts).
    # C35 Fast Mode: this guardrail is SKIPPED entirely — a FINAL ANSWER with
    # wants_chart=True and no chart finalizes immediately instead of forcing one
    # extra iteration. Charts are NOT disabled outright: an echart(...) call the
    # model makes on its own within the tightened budget still renders. This is
    # strictly a removal of the FORCED extra iteration, never charting itself.
    if (
        not state.get("fast_mode")
        and is_final
        and state.get("wants_chart")
        and not state.get("charts")
        and state.get("chart_force_count", 0) < 2
    ):
        return "plan_action"
    if is_final:
        return "finalize"
    return "execute_action"


def _consecutive_errors(action_history: list[dict]) -> int:
    count = 0
    for step in reversed(action_history):
        if step.get("is_error"):
            count += 1
        else:
            break
    return count


def after_execute(state: AgentState) -> str:
    """execute_action -> handle_error / force_finalize / plan_action.

    force_finalize fires on 3 consecutive `is_error` OR `iteration_count >= max_iterations`.
    A recoverable execution error simply loops back to plan_action to self-correct.
    """
    if state.get("error"):
        return "handle_error"

    # User pressed Stop mid-run: wrap up now instead of looping for more actions.
    if is_cancelled(state.get("run_id", "")):
        return "force_finalize"

    action_history = state.get("action_history") or []
    iteration = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 6)

    if _consecutive_errors(action_history) >= _MAX_CONSECUTIVE_ERRORS:
        return "force_finalize"
    if iteration >= max_iterations:
        return "force_finalize"
    return "plan_action"
