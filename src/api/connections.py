"""External database connector routes (C36, Phase 9, BETA).

`GET /connections/status`, `POST /connections/check`, `POST /connections/import`,
`POST /connections/{dataset_id}/resync` — a one-time snapshot-pull
data-LOADING mechanism (`src/connectors/`), never a live-query path. Every
route except `GET /connections/status` is gated behind
`AGENT_ENABLE_DB_CONNECTORS` (403 `connectors_disabled` when off).

Credential hygiene: the raw connection URI (with password) is read ONLY at
connect time inside a connector (`DatasetURI.raw()`), and is written to
exactly one DB column (`datasets.source_uri_raw`, for resync). Every response
built here is assembled field-by-field — never `row.__dict__` — so
`source_uri_raw` never leaves this process via an API response.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api._common import ok, api_error
from api._parquet import _safe_to_parquet
from api.datasets import _list_item
from config.settings import get_settings
from connectors.base import DatasetConnectionError, get_connector
from connectors.uri import DatasetURI
from db.models import DatasetRow
from db.session import get_session
from graph.nodes import invalidate_dataset_cache
from observability.events import get_logger

router = APIRouter()
logger = get_logger("api.connections")

# repo root = src/api/connections.py -> 3 parents up
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = _REPO_ROOT / "uploads"

_SUPPORTED_TYPES = {"postgresql"}


def _ensure_uploads_dir() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _require_enabled() -> None:
    if not get_settings().enable_db_connectors:
        raise api_error(
            "connectors_disabled",
            "External database connectors are disabled (set AGENT_ENABLE_DB_CONNECTORS=true).",
            403,
        )


class ConnectionCheckRequest(BaseModel):
    type: str
    uri: str


class ImportTableSpec(BaseModel):
    table_name: str
    alias: str | None = None
    filter: str | None = None


class ConnectionImportRequest(BaseModel):
    type: str
    uri: str
    tables: list[ImportTableSpec] = Field(default_factory=list)


@router.get("/connections/status")
def connections_status() -> dict:
    """Always reachable — even with the flag off — so the frontend can hide the BETA affordance."""
    return ok({"enabled": get_settings().enable_db_connectors})


@router.post("/connections/check")
def connections_check(body: ConnectionCheckRequest) -> dict:
    """Test a connection + discover its tables. Nothing is persisted by this call."""
    _require_enabled()
    if body.type not in _SUPPORTED_TYPES:
        raise api_error("unsupported_type", f"Unsupported connector type: {body.type!r}", 400)

    connector = get_connector({"type": body.type, "uri": body.uri})
    try:
        connector.connection_check()
        tables = connector.discover_tables()
        try:
            relationships = connector.discover_relationships()
        except Exception:  # noqa: BLE001 — relationships are best-effort, never block check
            relationships = []
    except DatasetConnectionError as exc:
        raise api_error("connection_failed", str(exc), 400)
    finally:
        connector.close()

    return ok({"tables": tables, "relationships": relationships})


def _register_pulled_table(
    session: Session,
    *,
    df,
    table_name: str,
    alias: str | None,
    source_type: str,
    uri: DatasetURI,
) -> str:
    """Register a pulled table exactly like an uploaded file (C36 provenance fields added).

    Writes `uploads/{new_id}.csv` + `.parquet`, creates a `datasets` row with
    `origin="connected"`. `source_uri_raw` is written here (the ONE place it is
    ever persisted) — read from `uri.raw()`, never logged.
    """
    filename = (alias or table_name).strip() or table_name
    columns_json = [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]

    row = DatasetRow(
        filename=filename,
        file_path="",  # set below once id is known
        row_count=int(df.shape[0]),
        col_count=int(df.shape[1]),
        columns_json=columns_json,
        content_hash="",  # set below from the written CSV bytes
        format="csv",
        context=None,
        origin="connected",
        source_type=source_type,
        source_uri_display=uri.display(),
        source_table_name=table_name,
        source_uri_raw=uri.raw(),
    )
    session.add(row)
    session.flush()  # assigns row.id
    dataset_id = row.id

    _ensure_uploads_dir()
    csv_path = UPLOADS_DIR / f"{dataset_id}.csv"
    parquet_path = UPLOADS_DIR / f"{dataset_id}.parquet"
    df.to_csv(csv_path, index=False)
    _safe_to_parquet(df, parquet_path)

    row.file_path = str(csv_path)
    row.parquet_path = str(parquet_path)
    row.content_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    return dataset_id


@router.post("/connections/import")
def connections_import(
    body: ConnectionImportRequest, session: Session = Depends(get_session)
) -> dict:
    """Pull + register each requested table independently (one failure never aborts the rest)."""
    _require_enabled()
    if body.type not in _SUPPORTED_TYPES:
        raise api_error("unsupported_type", f"Unsupported connector type: {body.type!r}", 400)
    if not body.tables:
        raise api_error("unsupported_type", "No tables were requested for import.", 400)

    uri = DatasetURI(body.uri)
    connector = get_connector({"type": body.type, "uri": body.uri})

    # Re-validate the connection BEFORE attempting any table pulls — if this
    # fails, no tables are attempted at all (per spec/api.md).
    try:
        connector.connection_check()
    except DatasetConnectionError as exc:
        connector.close()
        raise api_error("connection_failed", str(exc), 400)

    results: list[dict] = []
    for spec in body.tables:
        try:
            df = connector.pull_table(spec.table_name, spec.filter)
            dataset_id = _register_pulled_table(
                session,
                df=df,
                table_name=spec.table_name,
                alias=spec.alias,
                source_type=body.type,
                uri=uri,
            )
            session.commit()
            results.append(
                {"table_name": spec.table_name, "status": "ok", "dataset_id": dataset_id}
            )
            logger.info(
                "connection_table_imported", table_name=spec.table_name, dataset_id=dataset_id
            )
        except DatasetConnectionError as exc:
            session.rollback()
            results.append({"table_name": spec.table_name, "status": "error", "message": str(exc)})
            logger.warning(
                "connection_table_import_failed", table_name=spec.table_name, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 — one table's failure must not abort the others
            session.rollback()
            results.append({"table_name": spec.table_name, "status": "error", "message": str(exc)})
            logger.warning(
                "connection_table_import_failed", table_name=spec.table_name, error=str(exc)
            )

    connector.close()
    return ok({"results": results})


@router.post("/connections/{dataset_id}/resync")
def connections_resync(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    """Re-pull `source_table_name` and rewrite the dataset's files in place (mirrors `/re-derive`)."""
    _require_enabled()
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise api_error("not_found", f"Dataset {dataset_id} not found", 404)
    if row.origin != "connected" or not row.source_uri_raw or not row.source_table_name:
        raise api_error(
            "not_connected",
            "This dataset was not imported from a database connection.",
            400,
        )

    connector = get_connector({"type": row.source_type, "uri": row.source_uri_raw})
    try:
        connector.connection_check()
        df = connector.pull_table(row.source_table_name)
    except DatasetConnectionError as exc:
        raise api_error("resync_error", str(exc), 400)
    finally:
        connector.close()

    _ensure_uploads_dir()
    csv_path = UPLOADS_DIR / f"{dataset_id}.csv"
    parquet_path = UPLOADS_DIR / f"{dataset_id}.parquet"
    try:
        df.to_csv(csv_path, index=False)
        _safe_to_parquet(df, parquet_path)
    except Exception as exc:  # noqa: BLE001 — disk write failure
        raise api_error("resync_error", f"Could not write re-synced files: {exc}", 400)

    row.row_count = int(df.shape[0])
    row.col_count = int(df.shape[1])
    row.columns_json = [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]
    row.content_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    row.file_path = str(csv_path)
    row.parquet_path = str(parquet_path)

    # Evict the stale cached DataFrame so subsequent session turns load fresh data.
    invalidate_dataset_cache(dataset_id)

    item = _list_item(row, session)
    logger.info("dataset_resynced", dataset_id=dataset_id, rows=row.row_count)
    return ok(item)
