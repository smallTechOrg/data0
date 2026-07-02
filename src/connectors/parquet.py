"""ParquetConnector — the internal connector wrapping the EXISTING upload store (C36).

`POST /upload` remains the ONLY way to create an internally-uploaded dataset;
this class exists purely so the connector seam is genuinely pluggable
end-to-end (the internal store round-trips through the same abstraction an
external engine does). It is never called from any new HTTP route — only
exercised by unit tests and `connectors.base.get_connector` itself.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import select

from connectors.base import DatasetConnectionError, DatasetConnector
from db.models import DatasetRow
from db.session import create_db_session


class ParquetConnector(DatasetConnector):
    """Reads from the existing `datasets` table + its on-disk parquet/CSV files."""

    def connection_check(self) -> None:
        # The internal store has nothing external to probe — opening (and
        # closing) a DB session is the whole check.
        with create_db_session():
            pass

    def discover_tables(self) -> list[dict]:
        tables: list[dict] = []
        with create_db_session() as session:
            rows = session.execute(
                select(DatasetRow).order_by(DatasetRow.created_at.desc())
            ).scalars().all()
            for row in rows:
                columns = row.columns_json or []
                names: list[str] = []
                schema: list[dict] = []
                for entry in columns:
                    if isinstance(entry, dict):
                        name = str(entry.get("name", ""))
                        dtype = str(entry.get("dtype", "object"))
                    else:
                        name = str(entry)
                        dtype = "object"
                    names.append(name)
                    schema.append({"name": name, "dtype": dtype, "nullable": True})
                tables.append(
                    {
                        "table_name": row.filename,
                        "column_names": names,
                        "schema": schema,
                        "row_count": row.row_count,
                    }
                )
        return tables

    def pull_table(self, table_name: str, filter: str | None = None) -> pd.DataFrame:
        with create_db_session() as session:
            row = session.execute(
                select(DatasetRow).where(DatasetRow.filename == table_name)
            ).scalars().first()
            if row is None:
                raise DatasetConnectionError(
                    f"No internal dataset named {table_name!r}."
                )
            parquet_path = row.parquet_path
            file_path = row.file_path

        path: str | None = None
        if parquet_path and Path(parquet_path).exists():
            path = parquet_path
        elif file_path and Path(file_path).exists():
            path = file_path
        if not path:
            raise DatasetConnectionError(
                f"Dataset {table_name!r} has no data file on disk."
            )

        try:
            df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001 — surfaced as a connector error
            raise DatasetConnectionError(f"Could not read {table_name!r}: {exc}")

        if filter:
            try:
                df = df.query(filter)
            except Exception as exc:  # noqa: BLE001
                raise DatasetConnectionError(f"Invalid filter for {table_name!r}: {exc}")
        return df
