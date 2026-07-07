"""Phase 13 Item A — un-swallowed commit failures on the upload paths (offline).

Stub provider + isolated SQLite, ZERO network / ZERO LLM calls. Proves the
Phase-13 hardening: a `session.commit()` FAILURE mid-upload used to be logged
as a warning while the route still returned HTTP 200 `ok(...)` / per-sheet
`status:"ok"` for a row that was never persisted. Now:

  * `POST /upload`        -> HTTP 500 `write_failed`, nothing persisted.
  * `POST /upload/sheets` -> the failing sheet degrades to `status:"error"`
    (its transaction rolled back), while sibling sheets in the SAME request
    still import as `status:"ok"` — no session poisoning (C36 per-item
    independence precedent).

A `trigger_describe_async` (C30 fire-and-forget notes) failure stays
warn-and-continue: the dataset IS persisted, so the upload still returns
`ok(...)`.
"""
import io

import pytest
from openpyxl import Workbook
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Pin the offline stub provider regardless of any key present in `.env`."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    import config.settings as m
    m._settings = None


@pytest.fixture(autouse=True)
def _clear_staging():
    """The staging store is process-global — clear it around every test."""
    from api import upload_sheets
    upload_sheets._staging.clear()
    yield
    upload_sheets._staging.clear()


@pytest.fixture
def _tmp_uploads(tmp_path, monkeypatch):
    """Redirect dataset file writes to a per-test dir (keeps real uploads/ clean)."""
    import api.upload as upload_module

    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(upload_module, "UPLOADS_DIR", uploads_dir)
    return uploads_dir


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ROWS_2023 = [["value", "label"], [10, "a"], [20, "b"]]
_ROWS_2024 = [["value", "label"], [30, "c"], [40, "d"]]


def _xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_xlsx(client, sheets, *, name="wb.xlsx"):
    files = {"file": (name, io.BytesIO(_xlsx_bytes(sheets)), _XLSX_MIME)}
    return client.post("/upload", files=files)


def _upload_csv(client, *, name="data.csv", body=b"value,label\n10,a\n20,b\n"):
    files = {"file": (name, io.BytesIO(body), "text/csv")}
    return client.post("/upload", files=files)


def _list_dataset_ids(client) -> list[str]:
    return [d["id"] for d in client.get("/datasets").json()["data"]]


def _get_dataset_row(engine, dataset_id):
    from db.models import DatasetRow

    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as s:
        return s.get(DatasetRow, dataset_id)


# --- POST /upload -----------------------------------------------------------


def test_upload_commit_failure_returns_500_write_failed(
    api_client, _tmp_uploads, monkeypatch
):
    """A failing `session.commit()` surfaces as 500 `write_failed`, not a false 200,
    and the un-persisted row is rolled back (never listed)."""
    real_commit = OrmSession.commit

    def boom_commit(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(OrmSession, "commit", boom_commit)

    r = _upload_csv(api_client)
    assert r.status_code == 500, r.text
    assert r.json()["detail"]["code"] == "write_failed"

    # Restore commit so the read-back request can persist nothing-yet-persisted.
    monkeypatch.setattr(OrmSession, "commit", real_commit)
    assert _list_dataset_ids(api_client) == []  # rolled back — never persisted


def test_upload_notes_trigger_failure_still_returns_ok(
    api_client, _isolated_db, _tmp_uploads, monkeypatch
):
    """A C30 notes-trigger failure is warn-and-continue: the dataset IS persisted
    and the route still returns `ok(...)` (the trigger must NOT fail the upload)."""
    import api.upload as upload_module

    def boom_trigger(dataset_id):
        raise RuntimeError("simulated notes-trigger failure")

    monkeypatch.setattr(upload_module, "trigger_describe_async", boom_trigger)

    r = _upload_csv(api_client)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["dataset_id"]
    assert data["auto_notes_status"] == "pending"

    # Persisted for real despite the trigger blowing up.
    assert data["dataset_id"] in _list_dataset_ids(api_client)
    row = _get_dataset_row(_isolated_db, data["dataset_id"])
    assert row is not None
    assert row.row_count == 2


def test_upload_happy_path_persists_and_fires_trigger(
    api_client, _isolated_db, _tmp_uploads, monkeypatch
):
    """Baseline: commit succeeds -> the row persists, the notes trigger fires once,
    and the response is the normal `ok(...)` payload (byte-identical outcome)."""
    import api.upload as upload_module

    fired: list[str] = []
    monkeypatch.setattr(
        upload_module, "trigger_describe_async", lambda ds_id: fired.append(ds_id)
    )

    r = _upload_csv(api_client)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["row_count"] == 2
    assert data["columns"] == ["value", "label"]
    assert fired == [data["dataset_id"]]  # trigger fired exactly once
    assert data["dataset_id"] in _list_dataset_ids(api_client)
    assert (_tmp_uploads / f"{data['dataset_id']}.csv").exists()
    assert (_tmp_uploads / f"{data['dataset_id']}.parquet").exists()


# --- POST /upload/sheets — per-sheet commit isolation -----------------------


def test_sheets_commit_failure_isolated_per_sheet(
    api_client, _isolated_db, _tmp_uploads, monkeypatch
):
    """A commit failure on ONE sheet degrades to `status:"error"` (rolled back)
    while a sibling sheet in the SAME request still imports `status:"ok"` — the
    failed sheet does not poison the transaction for later sheets."""
    up = _upload_xlsx(api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024})
    token = up.json()["data"]["staging_token"]

    real_commit = OrmSession.commit

    def flaky_commit(self):
        # The row is set dirty (file_path assigned) after flush, so it is visible
        # in `session.dirty` at commit time — fail ONLY the 2023 sheet's commit.
        for obj in self.dirty:
            if str(getattr(obj, "filename", "")).endswith("— 2023"):
                raise RuntimeError("simulated commit failure for 2023")
        return real_commit(self)

    monkeypatch.setattr(OrmSession, "commit", flaky_commit)

    r = api_client.post(
        "/upload/sheets",
        json={
            "staging_token": token,
            "sheets": [{"sheet_name": "2023"}, {"sheet_name": "2024"}],
        },
    )
    assert r.status_code == 200, r.text  # per-item independence: the CALL succeeds
    results = {res["sheet_name"]: res for res in r.json()["data"]["results"]}

    # 2023 committed-failed -> isolated per-sheet error, nothing persisted for it.
    assert results["2023"]["status"] == "error", results
    assert results["2023"]["message"]
    assert "dataset" not in results["2023"]

    # 2024 was NOT poisoned by 2023's failure -> imported for real.
    assert results["2024"]["status"] == "ok", results
    imported_id = results["2024"]["dataset"]["dataset_id"]

    monkeypatch.setattr(OrmSession, "commit", real_commit)
    listed = _list_dataset_ids(api_client)
    assert imported_id in listed  # sibling persisted
    # Exactly one dataset landed — the failed sheet left no phantom row.
    row_2024 = _get_dataset_row(_isolated_db, imported_id)
    assert row_2024 is not None
    assert row_2024.source_table_name == "2024"
    assert not any(
        (r_ := _get_dataset_row(_isolated_db, ds_id)) is not None
        and r_.source_table_name == "2023"
        for ds_id in listed
    )
