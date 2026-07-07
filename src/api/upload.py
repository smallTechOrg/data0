"""`POST /upload` — register an uploaded data file as a dataset (Phase 2 + 4 + 12).

Parses the file with pandas by extension, computes a sha256 of the raw bytes,
duplicate-checks against existing `datasets` rows (C10), persists a CSV + Parquet
copy under `uploads/`, and creates a `DatasetRow` (origin=uploaded). Phase 4 (C30):
the new row is marked `auto_notes_status="pending"` and an async fire-and-forget
notes job (`trigger_describe_async`) is started after the dataset is committed —
it never blocks or fails the upload.

Phase 12 (C38): an `.xlsx`/`.xls` workbook is enumerated with `sheet_name=None`.
A workbook with >= 2 NON-EMPTY sheets persists nothing here — its raw bytes are
stashed in the in-memory staging store (`src/api/upload_sheets.py`) and the
response is the `type:"multi_sheet"` inspect variant (staging token + per-sheet
metadata); chosen sheets are then imported via `POST /upload/sheets`. A workbook
with exactly ONE non-empty sheet keeps today's EXACT single-shot contract (no
`type` key, unchanged filename, whole-file raw-bytes hash, upload-time C10
dedup); zero non-empty sheets -> 400 `empty_file`. The row-registration logic is
factored into `register_dataset` so the sheet-commit route reuses it verbatim.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import ok, api_error
from db.models import DatasetRow
from db.session import get_session
from graph.describe import trigger_describe_async
from observability.events import get_logger

router = APIRouter()
logger = get_logger("api.upload")

# repo root = src/api/upload.py -> 3 parents up
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = _REPO_ROOT / "uploads"

# extension -> (format label, pandas reader)
_EXT_TO_FORMAT = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".txt": "txt",
    ".json": "json",
    ".xlsx": "excel",
    ".xls": "excel",
}


def _ensure_uploads_dir() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _parse_dataframe(raw: bytes, ext: str) -> pd.DataFrame:
    """Parse raw bytes into a DataFrame by extension (non-excel formats).

    Excel is handled separately via `read_excel_sheets` (C38 enumerates ALL
    sheets, not just sheet 0). Raises ValueError on failure.
    """
    buf = io.BytesIO(raw)
    if ext == ".csv":
        return pd.read_csv(buf)
    if ext in (".tsv", ".txt"):
        return pd.read_csv(buf, sep="\t")
    if ext == ".json":
        # Handle the three JSON shapes the spec requires (D9):
        #   1. records-list: [{col: val, ...}, ...]  — default orient
        #   2. column-keyed / dict-of-lists: {col: [val, ...], ...}
        #   3. split-oriented: {"columns": [...], "data": [...]}
        #
        # pandas auto-detects shape 2 correctly with the default orient.
        # Shape 3 is silently misparsed by the default orient (the keys
        # "columns" and "data" become literal column names), so we peek at
        # the raw JSON to detect it before calling read_json. (D9)
        import json as _json  # noqa: PLC0415

        try:
            _peek = _json.loads(raw)
        except Exception:
            _peek = None

        if (
            isinstance(_peek, dict)
            and "columns" in _peek
            and "data" in _peek
        ):
            # Looks like split orientation — parse explicitly so we get the
            # right column names rather than a "columns"/"data" column frame.
            return pd.read_json(io.BytesIO(raw), orient="split")

        # For records-list and column-keyed (dict-of-lists), the default
        # orient works correctly; fall back to orient="columns" on ValueError.
        first_exc: Exception | None = None
        for orient in (None, "columns"):
            try:
                kwargs: dict = {} if orient is None else {"orient": orient}
                return pd.read_json(io.BytesIO(raw), **kwargs)
            except ValueError as exc:
                if first_exc is None:
                    first_exc = exc
        raise first_exc  # type: ignore[misc]
    raise ValueError(f"Unsupported extension: {ext}")


def read_excel_sheets(
    raw: bytes, ext: str, sheet_names: list[str] | None
) -> dict[str, pd.DataFrame]:
    """Parse workbook sheets as `{sheet_name: DataFrame}` (C38).

    `sheet_names=None` enumerates ALL sheets (the inspect step); a list parses
    only the requested sheets (the commit step). `.xls` uses `engine="xlrd"`
    explicitly — pandas cannot auto-detect the engine from a BytesIO stream
    (D13). Raises on unparseable bytes / unknown sheet names.
    """
    kwargs: dict = {"engine": "xlrd"} if ext == ".xls" else {}
    return pd.read_excel(io.BytesIO(raw), sheet_name=sheet_names, **kwargs)


def _is_empty_frame(df: pd.DataFrame) -> bool:
    """A sheet/table is empty when it has 0 rows or 0 columns after parse."""
    return df.shape[0] == 0 or df.shape[1] == 0


def find_duplicate(
    session: Session, *, filename: str, content_hash: str
) -> dict | None:
    """C10 duplicate check: content-hash match first, then name-only match.

    Returns `{match_type, existing_dataset_id, existing_filename}` or None.
    The caller shapes the delivery: a 409 for whole-file uploads, a per-sheet
    `status:"duplicate"` result for C38 sheet imports.
    """
    # --- Pass 1: content-hash match (same bytes / same canonical CSV) ---
    hash_match = session.execute(
        select(DatasetRow).where(DatasetRow.content_hash == content_hash)
    ).scalars().first()
    if hash_match is not None:
        same_name = hash_match.filename == filename
        return {
            "match_type": "content_and_name" if same_name else "content",
            "existing_dataset_id": hash_match.id,
            "existing_filename": hash_match.filename,
        }

    # --- Pass 2: filename match with different content (name-only duplicate) ---
    name_match = session.execute(
        select(DatasetRow).where(
            DatasetRow.filename == filename,
            DatasetRow.content_hash != content_hash,
        )
    ).scalars().first()
    if name_match is not None:
        return {
            "match_type": "name",
            "existing_dataset_id": name_match.id,
            "existing_filename": name_match.filename,
        }
    return None


def register_dataset(
    session: Session,
    df: pd.DataFrame,
    *,
    filename: str,
    fmt: str,
    content_hash: str,
    context: str | None,
    source_type: str | None = None,
    source_uri_display: str | None = None,
    source_table_name: str | None = None,
) -> dict:
    """Create the `datasets` row, write CSV + Parquet, commit, fire C30 notes.

    Shared by the single-file upload path and the C38 per-sheet commit route
    (`src/api/upload_sheets.py` — which passes the `source_*` provenance
    kwargs; direct uploads leave them None). Raises HTTPException 500
    `write_failed` on a disk failure — per-sheet callers catch and roll back.
    Returns the single-upload response payload dict.
    """
    columns = [str(c) for c in df.columns]
    columns_json = [
        {"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns
    ]

    # Create the row first to get its id (drives the on-disk filenames).
    row = DatasetRow(
        filename=filename,
        file_path="",  # set below once id is known
        row_count=int(df.shape[0]),
        col_count=int(df.shape[1]),
        columns_json=columns_json,
        content_hash=content_hash,
        format=fmt,
        context=context,
        origin="uploaded",
        auto_notes_status="pending",  # C30: async notes job is fired below
        source_type=source_type,
        source_uri_display=source_uri_display,
        source_table_name=source_table_name,
    )
    session.add(row)
    session.flush()  # assigns row.id
    dataset_id = row.id

    csv_path = UPLOADS_DIR / f"{dataset_id}.csv"
    parquet_path = UPLOADS_DIR / f"{dataset_id}.parquet"
    try:
        _ensure_uploads_dir()
        df.to_csv(csv_path, index=False)
        df.to_parquet(parquet_path, index=False)
    except Exception as exc:
        logger.error("upload_write_failed", dataset_id=dataset_id, error=str(exc))
        raise api_error("write_failed", f"Failed to write dataset to disk: {exc}", 500)

    row.file_path = str(csv_path)
    row.parquet_path = str(parquet_path)

    logger.info("upload_ok", dataset_id=dataset_id, rows=row.row_count, cols=row.col_count)

    # C30: commit the dataset NOW so the async notes job (its own DB session) can
    # see the row, then fire it fire-and-forget. The trigger never raises/blocks;
    # if it somehow fails, the upload still succeeds.
    try:
        session.commit()
        trigger_describe_async(dataset_id)
    except Exception as exc:  # noqa: BLE001 — notes trigger must not fail the upload
        logger.warning("upload_notes_trigger_failed", dataset_id=dataset_id, error=str(exc))

    return {
        "dataset_id": dataset_id,
        "filename": filename,
        "format": fmt,
        "row_count": row.row_count,
        "col_count": row.col_count,
        "columns": columns,
        "context": context,
        "auto_notes_status": "pending",
    }


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    context: str | None = Form(default=None),
    notes_file: UploadFile | None = File(default=None),
    force: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    fmt = _EXT_TO_FORMAT.get(ext)
    if fmt is None:
        raise api_error(
            "bad_extension",
            f"Unsupported file type {ext!r}. Accepted: .csv .tsv .txt .json .xlsx .xls",
            400,
        )

    raw = await file.read()
    if not raw or not raw.strip():
        raise api_error("empty_file", "Uploaded file is empty.", 400)

    content_hash = hashlib.sha256(raw).hexdigest()

    # C16: resolve context from notes_file (wins) or form context field.
    resolved_context: str | None = context
    if notes_file is not None:
        notes_raw = await notes_file.read()
        notes_text = notes_raw.decode("utf-8", errors="replace").strip()
        # Truncate at 4000 chars per spec.
        resolved_context = notes_text[:4000]

    if fmt == "excel":
        # C38: enumerate ALL sheets and branch on the non-empty count.
        try:
            sheets = read_excel_sheets(raw, ext, None)
        except Exception as exc:  # pandas raises many shapes; treat all as unparseable
            raise api_error("unparseable_file", f"Could not parse file: {exc}", 400)

        non_empty = [name for name, sdf in sheets.items() if not _is_empty_frame(sdf)]
        if not non_empty:
            raise api_error("empty_file", "Uploaded file has no data rows/columns.", 400)

        if len(non_empty) >= 2:
            # Picker path: persist NOTHING, stash the raw bytes, return the
            # inspect variant. C10 dedup deliberately does NOT run here (there
            # is nothing to persist yet, and re-dropping the same workbook to
            # import another sheet must never 409); `force` is ignored.
            # Lazy import — upload_sheets imports helpers from this module, so
            # a top-level import here would be circular.
            from api.upload_sheets import (  # noqa: PLC0415
                STAGING_TTL_SECONDS,
                stash_workbook,
            )

            staging_token = stash_workbook(
                raw=raw, filename=filename, ext=ext, context=resolved_context
            )
            logger.info(
                "upload_multi_sheet_staged",
                filename=filename,
                sheet_count=len(sheets),
                non_empty_count=len(non_empty),
            )
            return ok(
                {
                    "type": "multi_sheet",
                    "staging_token": staging_token,
                    "filename": filename,
                    "sheets": [
                        {
                            "sheet_name": name,
                            "row_count": int(sdf.shape[0]),
                            "col_count": int(sdf.shape[1]),
                            "empty": _is_empty_frame(sdf),
                        }
                        for name, sdf in sheets.items()  # workbook order
                    ],
                    "context": resolved_context,
                    "expires_in_seconds": STAGING_TTL_SECONDS,
                }
            )

        # Exactly one non-empty sheet -> today's EXACT single-shot contract:
        # unchanged filename (no sheet suffix), whole-file raw-bytes hash,
        # upload-time C10 dedup, no provenance columns.
        df = sheets[non_empty[0]]
    else:
        # Parse with pandas; an unparseable / empty-table file is a 400.
        try:
            df = _parse_dataframe(raw, ext)
        except Exception as exc:  # pandas raises many shapes; treat all as unparseable
            raise api_error("unparseable_file", f"Could not parse file: {exc}", 400)

    if _is_empty_frame(df):
        raise api_error("empty_file", "Uploaded file has no data rows/columns.", 400)

    # Duplicate check (C10): detect by content hash first, then by filename.
    if not force:
        dup = find_duplicate(session, filename=filename, content_hash=content_hash)
        if dup is not None:
            message = (
                "A file with this name was already uploaded. Re-upload with force=true to keep both."
                if dup["match_type"] == "name"
                else "This file was already uploaded. Re-upload with force=true to keep both."
            )
            # Duplicate carries extra resolution fields beyond {code,message};
            # build the HTTPException directly to keep the same `detail` envelope.
            raise HTTPException(
                status_code=409,
                detail={"code": "duplicate_dataset", "message": message, **dup},
            )

    payload = register_dataset(
        session,
        df,
        filename=filename,
        fmt=fmt,
        content_hash=content_hash,
        context=resolved_context,
    )
    return ok(payload)
