"""Offline C38 suite — multi-sheet Excel import (Phase 12).

Stub provider + isolated SQLite, zero network. Workbooks are built in memory
with openpyxl. Covers the full Phase-12 gate list: the `type:"multi_sheet"`
inspect variant, the byte-identical single-sheet passthrough, the
one-non-empty-among-empty-tabs direct import, the all-empty 400, per-sheet
import/dedup/error independence on `POST /upload/sheets`, the staging
lifecycle (TTL sweep, cap eviction, token-not-consumed), and `.xls`/D13
parity (BIFF2 single-sheet unchanged; the multi-sheet `.xls` enumeration via
a monkeypatched `pd.read_excel`, because BIFF2 is structurally single-sheet).
"""
import hashlib
import io

import pandas as pd
import pytest
from openpyxl import Workbook
from sqlalchemy.orm import sessionmaker

from test_api_stub import _make_xls_bytes


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


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Row grids (header + data) used to build workbook sheets.
_ROWS_2023 = [["value", "label"], [10, "a"], [20, "b"]]
_ROWS_2024 = [["value", "label"], [30, "c"], [40, "d"], [50, "e"]]
_ROWS_2025 = [["value", "label"], [60, "f"]]


def _xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    """Build an in-memory .xlsx with the given `{sheet_name: rows}` (rows may be [])."""
    wb = Workbook()
    wb.remove(wb.active)  # drop the default "Sheet"
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_xlsx(client, sheets, *, name="wb.xlsx", form=None, query=""):
    files = {"file": (name, io.BytesIO(_xlsx_bytes(sheets)), _XLSX_MIME)}
    return client.post(f"/upload{query}", files=files, data=form)


def _get_dataset_row(engine, dataset_id):
    from db.models import DatasetRow

    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as s:
        return s.get(DatasetRow, dataset_id)


def _canonical_hash(rows: list[list]) -> str:
    df = pd.DataFrame(rows[1:], columns=rows[0])
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


# --- inspect variant (`POST /upload`) --------------------------------------


def test_multi_sheet_inspect_variant_persists_nothing(api_client):
    r = _upload_xlsx(
        api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024, "Scratch": []}
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "multi_sheet"
    assert data["staging_token"]
    assert data["filename"] == "wb.xlsx"
    assert data["context"] is None
    assert data["expires_in_seconds"] == 900
    # All sheets listed in workbook order with correct counts + empty flags.
    assert [s["sheet_name"] for s in data["sheets"]] == ["2023", "2024", "Scratch"]
    by_name = {s["sheet_name"]: s for s in data["sheets"]}
    assert by_name["2023"] == {
        "sheet_name": "2023", "row_count": 2, "col_count": 2, "empty": False,
    }
    assert by_name["2024"] == {
        "sheet_name": "2024", "row_count": 3, "col_count": 2, "empty": False,
    }
    assert by_name["Scratch"]["empty"] is True
    assert by_name["Scratch"]["row_count"] == 0
    # NOTHING persisted by the inspect step.
    assert api_client.get("/datasets").json()["data"] == []


def test_multi_sheet_inspect_echoes_resolved_context(api_client):
    r = _upload_xlsx(
        api_client,
        {"2023": _ROWS_2023, "2024": _ROWS_2024},
        form={"context": "workbook-level notes"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["context"] == "workbook-level notes"


def test_multi_sheet_redrop_never_409(api_client):
    """No C10 dedup on the inspect branch — re-dropping the same workbook must work."""
    sheets = {"2023": _ROWS_2023, "2024": _ROWS_2024}
    first = _upload_xlsx(api_client, sheets)
    second = _upload_xlsx(api_client, sheets)
    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        second.json()["data"]["staging_token"]
        != first.json()["data"]["staging_token"]
    )


# --- single-sheet passthrough (byte-identical to today) ---------------------


def test_single_sheet_passthrough_shape_and_dedup(api_client, _isolated_db):
    # Build the bytes ONCE — openpyxl saves are not byte-deterministic (zip
    # timestamps), and the dedup contract here is the whole-file RAW-BYTES hash.
    wb_bytes = _xlsx_bytes({"Sheet1": _ROWS_2023})
    files = {"file": ("wb.xlsx", io.BytesIO(wb_bytes), _XLSX_MIME)}
    r = api_client.post("/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    # Today's EXACT response shape — no `type` key, no sheet suffix.
    assert set(data.keys()) == {
        "dataset_id", "filename", "format", "row_count", "col_count",
        "columns", "context", "auto_notes_status",
    }
    assert data["filename"] == "wb.xlsx"
    assert data["format"] == "excel"
    assert data["row_count"] == 2
    assert data["col_count"] == 2
    assert data["columns"] == ["value", "label"]
    assert data["auto_notes_status"] == "pending"

    # Whole-file raw-bytes hash + provenance columns NOT set (exact-today contract).
    row = _get_dataset_row(_isolated_db, data["dataset_id"])
    assert row.source_type is None
    assert row.source_uri_display is None
    assert row.source_table_name is None
    assert row.source_uri_raw is None
    assert row.origin == "uploaded"

    # An identical re-upload (SAME bytes) still 409s exactly as before
    # (upload-time C10 dedup against the whole-file raw-bytes hash).
    dup = api_client.post(
        "/upload", files={"file": ("wb.xlsx", io.BytesIO(wb_bytes), _XLSX_MIME)}
    )
    assert dup.status_code == 409, dup.text
    detail = dup.json()["detail"]
    assert detail["code"] == "duplicate_dataset"
    assert detail["match_type"] == "content_and_name"
    assert detail["existing_dataset_id"] == data["dataset_id"]


def test_one_nonempty_sheet_among_empty_tabs_imports_directly(api_client):
    """Exactly one NON-EMPTY sheet -> no picker, direct single-shot import."""
    r = _upload_xlsx(api_client, {"Empty1": [], "Data": _ROWS_2024, "Empty2": []})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "type" not in data
    assert data["filename"] == "wb.xlsx"  # no sheet suffix
    assert data["row_count"] == 3
    assert data["columns"] == ["value", "label"]


def test_all_empty_workbook_returns_400_empty_file(api_client):
    r = _upload_xlsx(api_client, {"Empty1": [], "Empty2": []})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "empty_file"


# --- `POST /upload/sheets` — per-sheet import --------------------------------


def test_commit_imports_selected_sheets(api_client, _isolated_db, monkeypatch):
    import api.upload as upload_module

    triggered: list[str] = []
    monkeypatch.setattr(
        upload_module, "trigger_describe_async", lambda ds_id: triggered.append(ds_id)
    )

    up = _upload_xlsx(
        api_client,
        {"2023": _ROWS_2023, "2024": _ROWS_2024, "2025": _ROWS_2025},
        form={"context": "workbook-level notes"},
    )
    token = up.json()["data"]["staging_token"]

    long_override = "x" * 5000
    r = api_client.post(
        "/upload/sheets",
        json={
            "staging_token": token,
            "sheets": [
                {"sheet_name": "2023"},  # inherits the workbook context
                {"sheet_name": "2024", "context": "per-sheet override"},
                {"sheet_name": "2025", "context": long_override},  # truncated to 4000
            ],
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["filename"] == "wb.xlsx"
    results = {res["sheet_name"]: res for res in data["results"]}
    assert all(res["status"] == "ok" for res in results.values()), data

    # Response payloads carry the single-upload shape with the sheet naming.
    ds_2023 = results["2023"]["dataset"]
    assert ds_2023["filename"] == "wb.xlsx — 2023"
    assert ds_2023["format"] == "excel"
    assert ds_2023["row_count"] == 2
    assert ds_2023["columns"] == ["value", "label"]
    assert ds_2023["context"] == "workbook-level notes"
    assert ds_2023["auto_notes_status"] == "pending"
    assert results["2024"]["dataset"]["filename"] == "wb.xlsx — 2024"
    assert results["2024"]["dataset"]["context"] == "per-sheet override"
    assert len(results["2025"]["dataset"]["context"]) == 4000

    # DB rows: provenance columns, origin, per-sheet canonical-CSV hash.
    row_2023 = _get_dataset_row(_isolated_db, ds_2023["dataset_id"])
    assert row_2023.origin == "uploaded"
    assert row_2023.source_type == "excel"
    assert row_2023.source_uri_display == "wb.xlsx"
    assert row_2023.source_table_name == "2023"
    assert row_2023.source_uri_raw is None
    assert row_2023.content_hash == _canonical_hash(_ROWS_2023)
    assert row_2023.auto_notes_status == "pending"

    # CSV + Parquet on disk per imported sheet.
    for res in results.values():
        ds_id = res["dataset"]["dataset_id"]
        assert (upload_module.UPLOADS_DIR / f"{ds_id}.csv").exists()
        assert (upload_module.UPLOADS_DIR / f"{ds_id}.parquet").exists()

    # One async C30 notes job per imported sheet.
    assert sorted(triggered) == sorted(
        res["dataset"]["dataset_id"] for res in results.values()
    )


def test_commit_per_sheet_dedup_and_force(api_client):
    up = _upload_xlsx(api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024})
    token = up.json()["data"]["staging_token"]

    first = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2023"}]},
    )
    first_result = first.json()["data"]["results"][0]
    assert first_result["status"] == "ok"
    first_id = first_result["dataset"]["dataset_id"]

    # Re-importing the SAME sheet -> per-sheet duplicate (call itself stays 200).
    dup = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2023"}]},
    )
    assert dup.status_code == 200, dup.text
    dup_result = dup.json()["data"]["results"][0]
    assert dup_result["status"] == "duplicate"
    assert dup_result["match_type"] == "content_and_name"
    assert dup_result["existing_dataset_id"] == first_id
    assert dup_result["existing_filename"] == "wb.xlsx — 2023"
    assert dup_result["message"]

    # A DIFFERENT sheet from the same workbook is NEVER blocked.
    other = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2024"}]},
    )
    assert other.json()["data"]["results"][0]["status"] == "ok"

    # force:true bypasses the check -> a second row for the same sheet.
    forced = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2023"}], "force": True},
    )
    forced_result = forced.json()["data"]["results"][0]
    assert forced_result["status"] == "ok"
    assert forced_result["dataset"]["dataset_id"] != first_id


def test_commit_name_match_when_sheet_data_changed(api_client):
    """Same `workbook — sheet` name with different data -> match_type 'name'."""
    up_a = _upload_xlsx(api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024})
    token_a = up_a.json()["data"]["staging_token"]
    imported = api_client.post(
        "/upload/sheets",
        json={"staging_token": token_a, "sheets": [{"sheet_name": "2023"}]},
    )
    first_id = imported.json()["data"]["results"][0]["dataset"]["dataset_id"]

    # Same workbook filename, but the 2023 sheet now has DIFFERENT data.
    changed_2023 = [["value", "label"], [99, "z"]]
    up_b = _upload_xlsx(api_client, {"2023": changed_2023, "2024": _ROWS_2024})
    token_b = up_b.json()["data"]["staging_token"]
    r = api_client.post(
        "/upload/sheets",
        json={"staging_token": token_b, "sheets": [{"sheet_name": "2023"}]},
    )
    result = r.json()["data"]["results"][0]
    assert result["status"] == "duplicate"
    assert result["match_type"] == "name"
    assert result["existing_dataset_id"] == first_id


def test_commit_empty_and_unknown_sheets_error_independently(api_client):
    """A bad sheet yields a per-sheet error; siblings in the SAME call still import."""
    up = _upload_xlsx(
        api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024, "Scratch": []}
    )
    token = up.json()["data"]["staging_token"]

    r = api_client.post(
        "/upload/sheets",
        json={
            "staging_token": token,
            "sheets": [
                {"sheet_name": "Scratch"},   # empty
                {"sheet_name": "Nope"},      # unknown
                {"sheet_name": "2023"},      # fine
            ],
        },
    )
    assert r.status_code == 200, r.text  # per-item independence: the CALL succeeds
    results = {res["sheet_name"]: res for res in r.json()["data"]["results"]}
    assert results["Scratch"]["status"] == "error"
    assert results["Scratch"]["message"] == "Sheet is empty."
    assert results["Nope"]["status"] == "error"
    assert results["Nope"]["message"]
    assert results["2023"]["status"] == "ok"
    assert results["2023"]["dataset"]["filename"] == "wb.xlsx — 2023"


# --- staging lifecycle -------------------------------------------------------


def test_unknown_staging_token_404(api_client):
    r = api_client.post(
        "/upload/sheets",
        json={"staging_token": "no-such-token", "sheets": [{"sheet_name": "A"}]},
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "staging_expired"


def test_empty_selection_400(api_client):
    up = _upload_xlsx(api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024})
    token = up.json()["data"]["staging_token"]
    r = api_client.post("/upload/sheets", json={"staging_token": token, "sheets": []})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "empty_selection"


def test_ttl_sweep_expires_stashed_workbook(api_client, monkeypatch):
    from api import upload_sheets

    fake_now = [1000.0]
    monkeypatch.setattr(upload_sheets, "_clock", lambda: fake_now[0])

    up = _upload_xlsx(api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024})
    token = up.json()["data"]["staging_token"]
    assert token in upload_sheets._staging

    # Just inside the TTL: still importable.
    fake_now[0] = 1000.0 + 899.0
    ok_r = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2023"}]},
    )
    assert ok_r.status_code == 200, ok_r.text

    # Past the 15-min TTL: the opportunistic sweep drops the entry -> 404.
    fake_now[0] = 1000.0 + 901.0
    r = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2024"}]},
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "staging_expired"
    assert token not in upload_sheets._staging  # swept, not just rejected


def test_staging_cap_evicts_oldest(api_client):
    from api import upload_sheets

    sheets = {"2023": _ROWS_2023, "2024": _ROWS_2024}
    tokens = [
        _upload_xlsx(api_client, sheets, name=f"wb{i}.xlsx").json()["data"]["staging_token"]
        for i in range(5)
    ]
    # A 5th stashed workbook evicts the oldest; the store never exceeds 4.
    assert len(upload_sheets._staging) == 4
    assert tokens[0] not in upload_sheets._staging

    oldest = api_client.post(
        "/upload/sheets",
        json={"staging_token": tokens[0], "sheets": [{"sheet_name": "2023"}]},
    )
    assert oldest.status_code == 404
    newest = api_client.post(
        "/upload/sheets",
        json={"staging_token": tokens[4], "sheets": [{"sheet_name": "2023"}]},
    )
    assert newest.status_code == 200
    assert newest.json()["data"]["results"][0]["status"] == "ok"


def test_token_survives_a_commit(api_client):
    """The token is NOT consumed — more sheets can be imported until expiry."""
    up = _upload_xlsx(api_client, {"2023": _ROWS_2023, "2024": _ROWS_2024})
    token = up.json()["data"]["staging_token"]

    first = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2023"}]},
    )
    assert first.json()["data"]["results"][0]["status"] == "ok"

    second = api_client.post(
        "/upload/sheets",
        json={"staging_token": token, "sheets": [{"sheet_name": "2024"}]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["results"][0]["status"] == "ok"


# --- .xls legacy parity (D13) -----------------------------------------------


def test_xls_single_sheet_biff2_unchanged(api_client):
    """A single-sheet BIFF2 .xls imports exactly as today (no picker, no `type`)."""
    xls_bytes = _make_xls_bytes(
        ["col_a", "col_b"], [[1, "alpha"], [2, "beta"]]
    )
    files = {"file": ("legacy.xls", io.BytesIO(xls_bytes), "application/vnd.ms-excel")}
    r = api_client.post("/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "type" not in data
    assert data["filename"] == "legacy.xls"
    assert data["format"] == "excel"
    assert data["row_count"] >= 1


def test_xls_multi_sheet_branch_uses_xlrd_engine(api_client, monkeypatch):
    """The multi-sheet .xls branch enumerates via `engine="xlrd", sheet_name=None`.

    BIFF2 (the only .xls buildable in memory without xlwt) is structurally
    single-sheet, so the enumeration branch is asserted through a monkeypatched
    `pd.read_excel` returning a two-sheet dict — per the Phase-12 gate.
    """
    calls: list[dict] = []
    df_a = pd.DataFrame({"x": [1, 2]})
    df_b = pd.DataFrame({"y": [3]})

    def fake_read_excel(buf, sheet_name=0, engine=None, **kwargs):
        calls.append({"sheet_name": sheet_name, "engine": engine})
        frames = {"A": df_a.copy(), "B": df_b.copy()}
        if sheet_name is None:
            return frames
        if isinstance(sheet_name, list):
            return {name: frames[name] for name in sheet_name}
        return df_a.copy()

    monkeypatch.setattr("api.upload.pd.read_excel", fake_read_excel)

    files = {
        "file": ("legacy.xls", io.BytesIO(b"fake-xls-bytes"), "application/vnd.ms-excel")
    }
    r = api_client.post("/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "multi_sheet"
    assert [s["sheet_name"] for s in data["sheets"]] == ["A", "B"]
    assert calls[0] == {"sheet_name": None, "engine": "xlrd"}

    # The commit path re-parses the requested sheets with the same engine.
    commit = api_client.post(
        "/upload/sheets",
        json={"staging_token": data["staging_token"], "sheets": [{"sheet_name": "B"}]},
    )
    assert commit.status_code == 200, commit.text
    result = commit.json()["data"]["results"][0]
    assert result["status"] == "ok"
    assert result["dataset"]["filename"] == "legacy.xls — B"
    assert result["dataset"]["row_count"] == 1
    assert calls[1] == {"sheet_name": ["B"], "engine": "xlrd"}
