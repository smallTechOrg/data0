"""Real-Gemini integration test for C38 multi-sheet Excel import (SCOPED).

Requires an LLM key in `.env` (skips otherwise). Deliberately ONE upload ->
ONE sheet import -> ONE real `/ask` round-trip, proving an imported sheet
behaves exactly like an uploaded CSV downstream (agent catalog, lazy load,
real analysis). Scoped because the Gemini key is free-tier quota-constrained
(spec/roadmap.md Phase 12 gate) — qa-auditor runs this exactly once.
"""
import io

import pytest
from openpyxl import Workbook


def _workbook_bytes() -> bytes:
    """Two non-empty sheets — triggers the multi-sheet inspect variant."""
    wb = Workbook()
    wb.remove(wb.active)
    sales = wb.create_sheet(title="sales_2024")
    for row in [["value"], [10], [20], [30], [40], [50]]:
        sales.append(row)
    other = wb.create_sheet(title="notes_tab")
    for row in [["comment"], ["ignore me"]]:
        other.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.usefixtures("_require_llm_key")
def test_multi_sheet_import_then_real_ask(api_client):
    # 1. Upload the workbook -> the C38 inspect variant (nothing persisted yet).
    files = {
        "file": (
            "report.xlsx",
            io.BytesIO(_workbook_bytes()),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    up = api_client.post("/upload", files=files)
    assert up.status_code == 200, up.text
    inspect = up.json()["data"]
    assert inspect["type"] == "multi_sheet"
    assert [s["sheet_name"] for s in inspect["sheets"]] == ["sales_2024", "notes_tab"]

    # 2. Import ONE sheet as its own dataset.
    commit = api_client.post(
        "/upload/sheets",
        json={
            "staging_token": inspect["staging_token"],
            "sheets": [{"sheet_name": "sales_2024"}],
        },
    )
    assert commit.status_code == 200, commit.text
    result = commit.json()["data"]["results"][0]
    assert result["status"] == "ok", result
    dataset = result["dataset"]
    assert dataset["filename"] == "report.xlsx — sales_2024"
    assert dataset["row_count"] == 5

    # 3. ONE real /ask about that sheet's content -> a completed, non-stub
    #    answer, proving the imported sheet is a first-class dataset.
    r = api_client.post(
        "/ask",
        json={
            "dataset_id": dataset["dataset_id"],
            "question": "What is the average of the value column?",
            "skip_clarification": True,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "answer"
    assert data["status"] == "completed"

    answer = data["answer_markdown"]
    assert answer and answer.strip(), "answer_markdown must be non-empty real prose"
    assert "[stub]" not in answer, f"stub answer — real provider not used: {answer!r}"
    assert "30" in answer, f"expected the average (30) in the answer: {answer!r}"
    assert dataset["dataset_id"] in data["dataset_ids"]
