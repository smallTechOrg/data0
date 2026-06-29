"""Real-Gemini integration test for per-step reasoning (C33, slice-5a).

Requires `AGENT_GEMINI_API_KEY` (or another LLM key) in `.env`. Auto-detect
selects the real provider. Drives upload -> ask through the `api_client`
TestClient and asserts the run completes with a non-empty answer AND at least one
`action_history` step carries a non-empty `reasoning` string (the plan prompt now
asks the model to prefix each action with a `REASONING:` line).

Tolerance: a real model may not put a `REASONING:` line on EVERY step, so we
assert >=1 step has it (the contract is graceful — absent reasoning reads back as
`""`), not that every step does.
"""
import io

import pytest


# A tiny dataset that takes at least one inspection/aggregation step to answer.
_SALES_CSV = (
    "product,price,qty\n"
    "apple,10,3\n"
    "orange,20,5\n"
    "banana,30,2\n"
    "pear,40,4\n"
)


@pytest.mark.usefixtures("_require_llm_key")
def test_ask_real_records_reasoning_on_a_step(api_client):
    files = {"file": ("sales.csv", io.BytesIO(_SALES_CSV.encode()), "text/csv")}
    up = api_client.post("/upload", files=files)
    assert up.status_code == 200, up.text
    dataset_id = up.json()["data"]["dataset_id"]

    r = api_client.post(
        "/ask",
        json={
            "dataset_id": dataset_id,
            "question": "What is the total quantity sold across all products?",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["type"] == "answer"
    assert data["status"] == "completed"

    answer = data["answer_markdown"]
    assert answer and answer.strip(), "answer_markdown must be non-empty real prose"
    assert "[stub]" not in answer, f"got a stub answer, real provider not used: {answer!r}"

    steps = data["steps"]
    assert len(steps) >= 1, "expected at least one action step"

    # Every step carries the reasoning key (default "" when absent).
    for step in steps:
        assert "reasoning" in step, f"step missing reasoning key: {step!r}"

    reasoned = [s for s in steps if (s.get("reasoning") or "").strip()]
    assert reasoned, (
        "expected >=1 step with a non-empty reasoning string; "
        f"steps={steps!r}"
    )
