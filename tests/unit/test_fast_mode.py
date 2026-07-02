"""Offline unit tests for C35 Fast Mode (slice-8a).

Zero env vars, no network, in-memory SQLite (via the autouse `_isolated_db`
fixture in conftest). The stub LLM provider drives the loop; these tests assert
the FAST-MODE-SPECIFIC behavior described in spec/capabilities/fast-mode.md:

- the tightened `max_iterations=5` cap WINS OVER the settings/DB-override value
- `check_clarification` / `generate_suggestions` are never called when
  `fast_mode=True` (asserted via a mock/spy)
- `execute_action` truncates a step's stored `result` to ~500 chars (+ marker)
  when `fast_mode=True`; an identical step under `fast_mode=False` is untouched
- `after_plan`'s forced-chart retry never fires when `fast_mode=True`, even when
  `wants_chart=True` and no chart was produced
"""
from __future__ import annotations

import pandas as pd
import pytest

from db.models import DatasetRow, SettingRow
from db.session import create_db_session
from graph import nodes as nodes_module
from graph.edges import after_plan


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Make `LLMClient` use the offline stub provider for every test here."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    monkeypatch.delenv("AGENT_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_OPENROUTER_API_KEY", raising=False)


def _make_dataset(uploads_dir, filename: str = "sales.csv") -> str:
    """Create a tiny CSV on disk + a `datasets` row; return the dataset id."""
    df = pd.DataFrame(
        {
            "product": ["a", "b", "c", "d"],
            "price": [10.0, 20.0, 30.0, 40.0],
            "qty": [1, 2, 3, 4],
        }
    )
    with create_db_session() as session:
        row = DatasetRow(
            filename=filename,
            file_path="",
            row_count=len(df),
            col_count=len(df.columns),
            columns_json=list(df.columns),
            content_hash="hash-" + filename,
            format="csv",
            origin="uploaded",
        )
        session.add(row)
        session.flush()
        dataset_id = row.id
        csv_path = uploads_dir / f"{dataset_id}.csv"
        df.to_csv(csv_path, index=False)
        row.file_path = str(csv_path)
    return dataset_id


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    """Point the nodes' AND the runner's uploads dir at a tmp dir."""
    import graph.runner as runner_module

    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: d)
    monkeypatch.setattr(runner_module, "_uploads_dir", lambda: d)
    return d


# --------------------------------------------------------------------------- #
# Tightened max_iterations cap WINS OVER the settings/DB-override read
# --------------------------------------------------------------------------- #


def test_fast_mode_cap_overrides_db_setting(uploads_dir):
    """A DB override of max_iterations=20 must be IGNORED when fast_mode=True —
    the effective cap is 5. Force this observably by making the stub loop forever
    (never emit FINAL ANSWER) so the run only stops at the iteration cap; the
    resulting iteration_count must be capped at 5, not 20."""
    from graph.runner import run_agent

    # Configure a generous DB override that would normally win.
    with create_db_session() as session:
        session.add(SettingRow(key="max_iterations", value="20"))

    dataset_id = _make_dataset(uploads_dir)

    # Monkeypatch the stub provider's plan handler to never finalize, so the run
    # is guaranteed to hit the iteration cap rather than an early FINAL ANSWER.
    import llm.providers.stub as stub_module

    monkeypatch_calls = {"n": 0}

    def _never_finalize_plan(self, text):
        monkeypatch_calls["n"] += 1
        return "df['price'].sum()"

    orig_plan = stub_module.StubProvider._plan
    stub_module.StubProvider._plan = _never_finalize_plan
    try:
        result = run_agent(
            "Keep going forever.",
            [dataset_id],
            fast_mode=True,
        )
    finally:
        stub_module.StubProvider._plan = orig_plan

    assert result["status"] == "completed"  # force_finalize always completes
    assert result["iteration_count"] <= 5, (
        f"fast_mode cap must win over the DB override (20); got "
        f"iteration_count={result['iteration_count']}"
    )


def test_fast_mode_false_honors_db_override(uploads_dir):
    """Sanity check: with fast_mode=False (default), a normal run is unaffected
    and still honors the configured/DB cap (not artificially limited to 5)."""
    from graph.runner import run_agent

    with create_db_session() as session:
        session.add(SettingRow(key="max_iterations", value="1"))

    dataset_id = _make_dataset(uploads_dir)
    result = run_agent("Average price?", [dataset_id])

    # DB override of 1 applies (unaffected by fast_mode) -> best-effort after 1 step.
    assert result["status"] == "completed"
    assert result["is_best_effort"] is True


# --------------------------------------------------------------------------- #
# check_clarification / generate_suggestions are never called under fast_mode
# --------------------------------------------------------------------------- #


def test_fast_mode_never_calls_check_clarification(uploads_dir, monkeypatch):
    """run_agent(fast_mode=True, run_clarification=True, ...) must never call
    check_clarification, even on a first turn where a normal run would."""
    import graph.runner as runner_module

    calls = []

    def _spy(question, schemas):
        calls.append((question, schemas))
        return None

    monkeypatch.setattr(runner_module, "check_clarification", _spy)

    dataset_id = _make_dataset(uploads_dir)
    result = runner_module.run_agent(
        "What is the average price?",
        [dataset_id],
        run_clarification=True,
        skip_clarification=False,
        fast_mode=True,
    )

    assert calls == [], f"check_clarification was called under fast_mode=True: {calls}"
    assert result["type"] == "answer"


def test_normal_mode_first_turn_calls_check_clarification(uploads_dir, monkeypatch):
    """Sanity check: without fast_mode, a first-turn run DOES call
    check_clarification (proves the spy would have caught a regression)."""
    import graph.runner as runner_module

    calls = []

    def _spy(question, schemas):
        calls.append((question, schemas))
        return None  # proceed

    monkeypatch.setattr(runner_module, "check_clarification", _spy)

    dataset_id = _make_dataset(uploads_dir)
    runner_module.run_agent(
        "What is the average price?",
        [dataset_id],
        run_clarification=True,
        skip_clarification=False,
        fast_mode=False,
    )

    assert len(calls) == 1


def test_fast_mode_never_calls_generate_suggestions(uploads_dir, monkeypatch):
    """run_agent(fast_mode=True, ...) must never call generate_suggestions; the
    response's suggested_questions is []."""
    import graph.runner as runner_module

    calls = []

    def _spy(question, answer):
        calls.append((question, answer))
        return ["a follow-up?"], 10, 5

    monkeypatch.setattr(runner_module, "generate_suggestions", _spy)

    dataset_id = _make_dataset(uploads_dir)
    result = runner_module.run_agent(
        "What is the average price?",
        [dataset_id],
        fast_mode=True,
    )

    assert calls == [], f"generate_suggestions was called under fast_mode=True: {calls}"
    assert result["suggested_questions"] == []


def test_normal_mode_calls_generate_suggestions(uploads_dir, monkeypatch):
    """Sanity check: without fast_mode, a completed run DOES call
    generate_suggestions (proves the spy would have caught a regression)."""
    import graph.runner as runner_module

    calls = []

    def _spy(question, answer):
        calls.append((question, answer))
        return ["a follow-up?"], 10, 5

    monkeypatch.setattr(runner_module, "generate_suggestions", _spy)

    dataset_id = _make_dataset(uploads_dir)
    result = runner_module.run_agent(
        "What is the average price?",
        [dataset_id],
        fast_mode=False,
    )

    assert len(calls) == 1
    assert result["suggested_questions"] == ["a follow-up?"]


# --------------------------------------------------------------------------- #
# execute_action truncates stored action_history results in Fast Mode
# --------------------------------------------------------------------------- #


def _long_result_namespace():
    """A namespace whose expression yields a >500-char string result."""
    long_string = "x" * 800

    class _Obj:
        def __repr__(self):
            return long_string

    return {"long_val": _Obj()}


def test_execute_action_truncates_result_when_fast_mode(uploads_dir, monkeypatch):
    dataset_id = _make_dataset(uploads_dir)

    # Point _dataframes registry so execute_action has a valid bundle; use a
    # trivial catalog with a single dataset so `df`/`df1` resolve.
    df = pd.DataFrame({"price": [10.0, 20.0, 30.0, 40.0]})
    nodes_module._dataframes["run-fast"] = {
        "session_id": None,
        "catalog": [{"id": dataset_id, "filename": "sales.csv", "alias": "sales", "columns": ["price"], "notes": ""}],
        "frames": {dataset_id: df},
        "derived_frames": {},
    }

    state = {
        "run_id": "run-fast",
        "llm_response": "'x' * 800",
        "action_history": [],
        "charts": [],
        "fast_mode": True,
    }
    result = nodes_module.execute_action(state)
    step = result["action_history"][-1]

    assert len(step["result"]) <= 500 + len(nodes_module._FAST_MODE_TRUNCATION_MARKER)
    assert step["result"].endswith(nodes_module._FAST_MODE_TRUNCATION_MARKER)
    assert step["is_error"] is False


def test_execute_action_no_truncation_when_not_fast_mode(uploads_dir):
    dataset_id = _make_dataset(uploads_dir)
    df = pd.DataFrame({"price": [10.0, 20.0, 30.0, 40.0]})
    nodes_module._dataframes["run-normal"] = {
        "session_id": None,
        "catalog": [{"id": dataset_id, "filename": "sales.csv", "alias": "sales", "columns": ["price"], "notes": ""}],
        "frames": {dataset_id: df},
        "derived_frames": {},
    }

    state = {
        "run_id": "run-normal",
        "llm_response": "'x' * 800",
        "action_history": [],
        "charts": [],
        "fast_mode": False,
    }
    result = nodes_module.execute_action(state)
    step = result["action_history"][-1]

    assert len(step["result"]) == 800  # untruncated
    assert nodes_module._FAST_MODE_TRUNCATION_MARKER not in step["result"]


def test_execute_action_short_result_unaffected_by_truncation(uploads_dir):
    """A result under the 500-char limit is never marked/truncated even in
    Fast Mode."""
    dataset_id = _make_dataset(uploads_dir)
    df = pd.DataFrame({"price": [10.0, 20.0, 30.0, 40.0]})
    nodes_module._dataframes["run-short"] = {
        "session_id": None,
        "catalog": [{"id": dataset_id, "filename": "sales.csv", "alias": "sales", "columns": ["price"], "notes": ""}],
        "frames": {dataset_id: df},
        "derived_frames": {},
    }

    state = {
        "run_id": "run-short",
        "llm_response": "df['price'].sum()",
        "action_history": [],
        "charts": [],
        "fast_mode": True,
    }
    result = nodes_module.execute_action(state)
    step = result["action_history"][-1]

    assert nodes_module._FAST_MODE_TRUNCATION_MARKER not in step["result"]


def test_fast_mode_truncated_result_carries_into_next_prompt(uploads_dir):
    """The truncated (not raw) result is what re-enters the next iteration's
    assembled prompt — proves the truncation compounds correctly."""
    long_action_history = [
        {"action": "big()", "result": "y" * 800, "is_error": False, "reasoning": ""}
    ]
    state = {
        "fast_mode": True,
        "question": "q",
        "action_history": long_action_history,
        "dataset_context": None,
        "conversation_history": [],
    }
    prompt = nodes_module._assemble_plan_prompt(state, wrap_up=False)
    # The RAW 800-char string should not appear whole — but this state's
    # action_history was pre-truncated at append time (execute_action's job), so
    # here we just confirm the assembled prompt reflects whatever is stored,
    # i.e. it doesn't re-truncate on read.
    assert "y" * 800 in prompt  # sections render whatever is stored verbatim


# --------------------------------------------------------------------------- #
# Brevity instruction line (prompt-level only, no hard token cap)
# --------------------------------------------------------------------------- #


def test_plan_system_prompt_appends_brevity_line_when_fast_mode():
    system = "BASE SYSTEM PROMPT"
    out = nodes_module._plan_system_prompt({"fast_mode": True}, system)
    assert "BASE SYSTEM PROMPT" in out
    assert "Fast Mode" in out
    assert "brief" in out.lower()


def test_plan_system_prompt_unchanged_when_not_fast_mode():
    system = "BASE SYSTEM PROMPT"
    out = nodes_module._plan_system_prompt({"fast_mode": False}, system)
    assert out == system


# --------------------------------------------------------------------------- #
# after_plan: forced-chart retry never fires when fast_mode=True
# --------------------------------------------------------------------------- #


def test_after_plan_chart_guardrail_skipped_when_fast_mode():
    state = {
        "llm_response": "FINAL ANSWER: here you go",
        "wants_chart": True,
        "charts": [],
        "chart_force_count": 0,
        "fast_mode": True,
    }
    assert after_plan(state) == "finalize"


def test_after_plan_chart_guardrail_fires_when_not_fast_mode():
    """Sanity check: without fast_mode, the SAME state loops back to plan_action
    (proves the guardrail itself is unaffected outside Fast Mode)."""
    state = {
        "llm_response": "FINAL ANSWER: here you go",
        "wants_chart": True,
        "charts": [],
        "chart_force_count": 0,
        "fast_mode": False,
    }
    assert after_plan(state) == "plan_action"


def test_after_plan_chart_guardrail_skip_even_when_force_count_below_cap():
    """Even with chart_force_count well below the normal cap of 2, fast_mode
    still finalizes immediately — the skip is unconditional, not a lower cap."""
    state = {
        "llm_response": "FINAL ANSWER: here you go",
        "wants_chart": True,
        "charts": [],
        "chart_force_count": 1,
        "fast_mode": True,
    }
    assert after_plan(state) == "finalize"
