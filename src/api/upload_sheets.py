"""C38 (Phase 12) — multi-sheet Excel staging store + `POST /upload/sheets`.

The inspect step in `src/api/upload.py` stashes a multi-sheet workbook's raw
bytes here (UUID token, 15-min TTL with an opportunistic sweep on each
stash/lookup, at most 4 staged workbooks — oldest evicted on overflow). This
route re-parses ONLY the requested sheets from the stash and registers each
one INDEPENDENTLY as its own dataset (C36's per-item precedent: one sheet's
failure never aborts the others; the call returns 200 with per-sheet results
even if every sheet failed). The token is NOT consumed by a commit — more
sheets can be imported from the same stash until TTL expiry.

The store is process-memory only: a server restart clears it and the user
simply re-drops the file (single-user local app). Whole-call errors are only
404 `staging_expired` and 400 `empty_selection`.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api._common import ok, api_error
from api.upload import find_duplicate, read_excel_sheets, register_dataset
from db.session import get_session
from observability.events import get_logger

router = APIRouter()
logger = get_logger("api.upload_sheets")

# --- in-memory staging store ----------------------------------------------

STAGING_TTL_SECONDS = 900  # 15 minutes
_MAX_STAGED_WORKBOOKS = 4

_DUPLICATE_MESSAGE = (
    "This sheet was already imported. Re-import with force=true to keep both."
)


@dataclass
class _StagedWorkbook:
    raw: bytes
    filename: str
    ext: str
    context: str | None  # C16-resolved workbook-level context (inherited per sheet)
    stashed_at: float


# token -> entry, in stash order (oldest first) so cap-eviction pops the front.
_staging: OrderedDict[str, _StagedWorkbook] = OrderedDict()


def _clock() -> float:
    """Staging clock — module-level indirection so tests can monkeypatch it."""
    return time.monotonic()


def _sweep() -> None:
    """Drop entries past the TTL (opportunistic — runs on each stash/lookup)."""
    now = _clock()
    expired = [
        token
        for token, entry in _staging.items()
        if now - entry.stashed_at > STAGING_TTL_SECONDS
    ]
    for token in expired:
        del _staging[token]
        logger.info("staging_entry_expired", staging_token=token)


def stash_workbook(
    *, raw: bytes, filename: str, ext: str, context: str | None
) -> str:
    """Stash a multi-sheet workbook's raw bytes; returns the staging token."""
    _sweep()
    token = str(uuid.uuid4())
    _staging[token] = _StagedWorkbook(
        raw=raw, filename=filename, ext=ext, context=context, stashed_at=_clock()
    )
    while len(_staging) > _MAX_STAGED_WORKBOOKS:
        evicted, _ = _staging.popitem(last=False)  # oldest evicted on overflow
        logger.info("staging_entry_evicted", staging_token=evicted)
    return token


def lookup_workbook(token: str) -> _StagedWorkbook | None:
    """Return the staged entry for `token`, or None if unknown/expired."""
    _sweep()
    return _staging.get(token)


# --- request models ---------------------------------------------------------


class SheetSelection(BaseModel):
    sheet_name: str
    # Per-sheet override of the inherited workbook-level context (C16; same
    # 4000-char silent truncation as upload-time notes).
    context: str | None = None


class SheetsImportRequest(BaseModel):
    staging_token: str
    sheets: list[SheetSelection] = Field(default_factory=list)
    force: bool = False


# --- route -------------------------------------------------------------------


def _parse_requested_sheets(
    entry: _StagedWorkbook, names: list[str]
) -> dict[str, pd.DataFrame | Exception]:
    """Parse the requested sheets from the stashed bytes.

    Batched first (one workbook parse for the common case); if the batched
    call raises (e.g. one unknown sheet name), fall back to per-sheet parses
    so ONE bad name degrades to ONE per-sheet error instead of failing the
    whole call (C36 per-item independence). Returns
    `{sheet_name: DataFrame | Exception}`.
    """
    unique = list(dict.fromkeys(names))
    try:
        frames = read_excel_sheets(entry.raw, entry.ext, unique)
        return {name: frames[name] for name in unique}
    except Exception:  # noqa: BLE001 — degrade to per-sheet isolation below
        out: dict[str, pd.DataFrame | Exception] = {}
        for name in unique:
            try:
                out[name] = read_excel_sheets(entry.raw, entry.ext, [name])[name]
            except Exception as exc:  # noqa: BLE001 — recorded as that sheet's error
                out[name] = exc
        return out


def _import_one_sheet(
    session: Session,
    *,
    entry: _StagedWorkbook,
    selection: SheetSelection,
    frames: dict[str, pd.DataFrame | Exception],
    force: bool,
) -> dict:
    """Import a single requested sheet; always returns a per-sheet result dict."""
    name = selection.sheet_name
    parsed = frames.get(name)
    if parsed is None or isinstance(parsed, Exception):
        detail = str(parsed) if parsed is not None else "Sheet not found in workbook."
        logger.warning("sheet_import_failed", sheet_name=name, error=detail)
        return {
            "sheet_name": name,
            "status": "error",
            "message": f"Could not read sheet: {detail}",
        }

    df = parsed
    if df.shape[0] == 0 or df.shape[1] == 0:
        return {"sheet_name": name, "status": "error", "message": "Sheet is empty."}

    # Dataset naming: display name AND the C10 name-dedup key — sibling sheets
    # never collide, re-importing the same sheet name-matches deterministically.
    sheet_filename = f"{entry.filename} — {name}"

    # C10 extension: per-sheet hash over the canonical CSV serialization — NOT
    # the workbook's raw bytes — so sibling sheets never dedup-block each other
    # and the same sheet re-imported from a re-saved workbook still matches.
    content_hash = hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()

    # C16: the per-sheet override wins over the inherited workbook context.
    context = selection.context[:4000] if selection.context else entry.context

    if not force:
        dup = find_duplicate(session, filename=sheet_filename, content_hash=content_hash)
        if dup is not None:
            return {
                "sheet_name": name,
                "status": "duplicate",
                "message": _DUPLICATE_MESSAGE,
                **dup,
            }

    try:
        dataset = register_dataset(
            session,
            df,
            filename=sheet_filename,
            fmt="excel",
            content_hash=content_hash,
            context=context,
            source_type="excel",
            source_uri_display=entry.filename,
            source_table_name=name,
        )
    except Exception as exc:  # noqa: BLE001 — one sheet's failure never aborts the others
        session.rollback()
        message = (
            exc.detail.get("message", str(exc))
            if isinstance(exc, HTTPException) and isinstance(exc.detail, dict)
            else str(exc)
        )
        logger.warning("sheet_import_failed", sheet_name=name, error=message)
        return {"sheet_name": name, "status": "error", "message": message}

    logger.info("sheet_imported", sheet_name=name, dataset_id=dataset["dataset_id"])
    return {"sheet_name": name, "status": "ok", "dataset": dataset}


@router.post("/upload/sheets")
def import_sheets(
    body: SheetsImportRequest, session: Session = Depends(get_session)
) -> dict:
    """Import chosen sheets from a staged workbook — each sheet independently."""
    entry = lookup_workbook(body.staging_token)
    if entry is None:
        raise api_error(
            "staging_expired",
            "Staged workbook not found or expired — re-drop the file.",
            404,
        )
    if not body.sheets:
        raise api_error("empty_selection", "No sheets were selected for import.", 400)

    frames = _parse_requested_sheets(entry, [s.sheet_name for s in body.sheets])

    results = [
        _import_one_sheet(
            session, entry=entry, selection=selection, frames=frames, force=body.force
        )
        for selection in body.sheets
    ]
    return ok({"filename": entry.filename, "results": results})
