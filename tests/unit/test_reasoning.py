"""Offline unit tests for per-step reasoning (C33, slice-5a).

Zero env vars, no network, in-memory SQLite (via the autouse `_isolated_db`
fixture in conftest). Covers two layers:

1. The pure `_split_reasoning` splitter — marker detection, case-insensitivity,
   leading-whitespace tolerance, multi-line body preservation, and the bare-reply
   fallback (`reasoning=""`, original text untouched).
2. `execute_action` end-to-end against a tiny in-memory DataFrame — a reply with
   a `REASONING:` line records the rationale AND executes the SAME `action`/`result`
   as the bare expression alone (execution is byte-for-byte unchanged).
"""
from __future__ import annotations

import pandas as pd
import pytest

from graph import nodes as nodes_module
from graph.nodes import _split_reasoning, execute_action


# --------------------------------------------------------------------------- #
# _split_reasoning (pure function)
# --------------------------------------------------------------------------- #


def test_split_reasoning_extracts_marker_and_remainder():
    reasoning, remainder = _split_reasoning("REASONING: inspect columns first\ndf.columns.tolist()")
    assert reasoning == "inspect columns first"
    assert remainder == "df.columns.tolist()"


def test_split_reasoning_bare_reply_is_unchanged():
    """The stub's bare expression: no marker -> empty reasoning + original text."""
    bare = "df.describe().to_string()"
    reasoning, remainder = _split_reasoning(bare)
    assert reasoning == ""
    assert remainder == bare  # byte-for-byte unchanged


def test_split_reasoning_is_case_insensitive():
    reasoning, remainder = _split_reasoning("reasoning: lower case marker\ndf.head()")
    assert reasoning == "lower case marker"
    assert remainder == "df.head()"

    reasoning, remainder = _split_reasoning("ReAsOnInG: mixed case\ndf.shape")
    assert reasoning == "mixed case"
    assert remainder == "df.shape"


def test_split_reasoning_tolerates_leading_whitespace():
    reasoning, remainder = _split_reasoning("   REASONING:   trimmed   \ndf.head()")
    assert reasoning == "trimmed"
    assert remainder == "df.head()"


def test_split_reasoning_preserves_multiline_body():
    text = "REASONING: build then save\nbase = df.head()\nsave_dataset(base, 'b', 'first rows')"
    reasoning, remainder = _split_reasoning(text)
    assert reasoning == "build then save"
    assert remainder == "base = df.head()\nsave_dataset(base, 'b', 'first rows')"


def test_split_reasoning_skips_leading_blank_lines():
    """A leading blank line before the marker is tolerated (first NON-EMPTY line)."""
    reasoning, remainder = _split_reasoning("\n\nREASONING: after blanks\ndf.columns.tolist()")
    assert reasoning == "after blanks"
    assert remainder == "df.columns.tolist()"


def test_split_reasoning_empty_and_no_marker():
    assert _split_reasoning("") == ("", "")
    # No marker on the first non-empty line -> untouched.
    text = "df['price'].mean()"
    assert _split_reasoning(text) == ("", text)


# --------------------------------------------------------------------------- #
# execute_action end-to-end (real eval against an in-memory DataFrame)
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_run(monkeypatch):
    """Seed the run-scoped `_dataframes` registry with a tiny frame.

    Uses the lazy-namespace bundle shape: a metadata-only `catalog` plus a
    pre-cached `frames` dict, so the lazy loader returns the frame WITHOUT any
    disk access (no DatasetRow needed). Yields the `run_id`; cleans the registry
    afterwards so tests stay isolated.
    """
    run_id = "r-reasoning-test"
    dataset_id = "ds-reasoning-test"
    df = pd.DataFrame({"price": [10.0, 20.0, 30.0, 40.0], "qty": [1, 2, 3, 4]})
    nodes_module._dataframes[run_id] = {
        "session_id": None,
        "catalog": [
            {
                "id": dataset_id,
                "alias": "sales",
                "filename": "sales.csv",
                "columns": ["price", "qty"],
                "notes": "",
            }
        ],
        "frames": {dataset_id: df},  # pre-cached -> loader returns it, no disk read
        "derived_frames": {},
    }
    yield run_id
    nodes_module._dataframes.pop(run_id, None)


def _run_step(run_id: str, llm_response: str) -> dict:
    """Run execute_action once for a given raw planner reply; return the new step."""
    state = {
        "run_id": run_id,
        "llm_response": llm_response,
        "iteration_count": 1,
        "action_history": [],
        "dataset_ids": [],
    }
    out = execute_action(state)
    return out["action_history"][-1]


def test_execute_action_records_reasoning_and_runs_same_code(seeded_run):
    """A `REASONING:` reply records the rationale AND executes the bare expression
    identically to running that expression with no reasoning line."""
    with_reasoning = _run_step(seeded_run, "REASONING: inspect columns first\ndf.columns.tolist()")
    bare = _run_step(seeded_run, "df.columns.tolist()")

    assert with_reasoning["reasoning"] == "inspect columns first"
    # Execution byte-for-byte identical to the bare reply.
    assert with_reasoning["action"] == bare["action"] == "df.columns.tolist()"
    assert with_reasoning["result"] == bare["result"]
    assert with_reasoning["is_error"] == bare["is_error"] is False
    # The bare reply records empty reasoning.
    assert bare["reasoning"] == ""


def test_execute_action_bare_stub_reply_has_empty_reasoning(seeded_run):
    """The stub's first action (`df.describe().to_string()`, no marker) parses to
    reasoning="" and runs unchanged."""
    step = _run_step(seeded_run, "df.describe().to_string()")
    assert step["reasoning"] == ""
    assert step["action"] == "df.describe().to_string()"
    assert step["is_error"] is False
    assert "price" in step["result"]


def test_execute_action_case_insensitive_marker(seeded_run):
    step = _run_step(seeded_run, "reasoning: lowercase works\ndf.shape")
    assert step["reasoning"] == "lowercase works"
    assert step["action"] == "df.shape"
    assert step["is_error"] is False


def test_execute_action_preserves_multiline_body(seeded_run):
    """A multi-line code body after the REASONING line is preserved and executed."""
    reply = "REASONING: total then describe\ntotal = df['price'].sum()\ntotal"
    step = _run_step(seeded_run, reply)
    assert step["reasoning"] == "total then describe"
    assert step["action"] == "total = df['price'].sum()\ntotal"
    assert step["is_error"] is False
    assert "100" in step["result"]  # 10+20+30+40
