from typing import TypedDict


class AgentState(TypedDict, total=False):
    """ReAct loop state (LangGraph). `total=False` per skeleton convention —
    nodes populate fields progressively. Never a dataclass/Pydantic model.
    """

    # Identity
    run_id: str                          # query_runs.id, set at initialisation

    # Input
    dataset_ids: list[str]               # ALL workspace datasets as the agent's catalog (it picks + lazily loads)
    dataset_context: str | None          # metadata-only catalog of all datasets, injected into the prompt
    session_id: str | None               # set when the run belongs to a conversation session
    question: str                        # the user's plain-English question
    conversation_history: list[dict]     # prior turns {question, answer} for the session

    # Pipeline data (populated progressively by nodes)
    action_history: list[dict]           # [{action, result, is_error, reasoning}] appended by execute_action
    iteration_count: int                 # incremented by plan_action
    llm_response: str                    # latest raw model reply (action or FINAL ANSWER)
    tokens_input: int                    # accumulated prompt tokens
    tokens_output: int                   # accumulated completion tokens
    tokens_cached: int                   # C39: accumulated cache-served prompt tokens (subset of tokens_input; plan_action + force_finalize only)
    charts: list[str]                    # ECharts `option` JSON strings captured in execute_action (via echart())
    prompt_component_chars: dict         # C29: CUMULATIVE per-bucket char counts summed across all plan_action calls

    # Output
    answer: str | None                   # final markdown answer (FINAL ANSWER stripped)
    selector_reasoning: str | None       # retained for API/DB compat; always None under agent-driven selection

    # Control
    error: str | None                    # set by any node on fatal failure -> handle_error
    error_message: str | None            # informational (e.g. "max_iterations") from force_finalize
    status: str                          # running | completed | failed
    max_iterations: int                  # per-run cap (from settings or override)

    # Chart guardrail (deterministic): when the question explicitly asks for a
    # chart, force ONE extra iteration demanding an echart(...) if a final reply
    # arrives with no chart produced. Capped so it can never loop forever.
    wants_chart: bool                    # set in setup from _wants_chart(question)
    chart_force_count: int               # times a final-without-chart was rejected

    # C35 Fast Mode: a per-request flag (never a settings/DB default for future
    # requests) that tightens the iteration cap, skips clarification/suggestions
    # (call-site decisions in runner.py), truncates action_history results, adds
    # a brevity prompt line, and disables the forced-chart-retry guardrail. The
    # completed run's value IS persisted on query_runs.fast_mode (see
    # graph/runner.py's run_agent) purely so the UI badge survives reload — that
    # is historical record-keeping, not a behavioral default. See
    # spec/capabilities/fast-mode.md.
    fast_mode: bool                      # set from the /ask request; default False
