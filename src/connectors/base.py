"""Database connector base class + registry (C36).

The import/resync path must never branch on connector type. Every connector
inherits from `DatasetConnector` and implements the same methods returning
the same shapes, so callers use any connector interchangeably without
checking its type. `get_connector` dispatches on `type` to the concrete
subclass. A new engine = one new subclass + one registry entry.

This is a one-time snapshot-pull data-LOADING seam, not a live-query path —
there is no `query`/`execute` method here, only `pull_table`.
"""
from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from connectors.uri import DatasetURI


class DatasetConnectionError(Exception):
    """A database/table could not be connected to / read. Messages are ALWAYS credential-free."""


class DatasetConnector(ABC):
    """How the app validates, inspects, and pulls a bounded snapshot from a database.

    Subclasses differ only in their internals (parquet vs postgresql, etc.);
    the method signatures and returned shapes are identical across all of them.
    """

    def __init__(self, server: dict) -> None:
        self._server = server
        self._uri = DatasetURI(server.get("uri") or "")

    # --- required (type-specific internals) -------------------------------

    @abstractmethod
    def connection_check(self) -> None:
        """Validate the store is reachable/readable; raise `DatasetConnectionError` on failure.

        Never leaks credentials — any raised message is built from
        `self._uri.display()`, never `.raw()`.
        """

    @abstractmethod
    def discover_tables(self) -> list[dict]:
        """Inspect the store and return its tables.

        `[{table_name, column_names, schema, row_count}]` — `schema` is
        `[{name, dtype, nullable}]`; `row_count` may be `None` when the
        connector does not cheaply know it. May be empty.
        """

    @abstractmethod
    def pull_table(self, table_name: str, filter: str | None = None) -> pd.DataFrame:
        """Pull a ONE-TIME bounded snapshot of `table_name` into a DataFrame.

        `filter`, when supplied, is a raw boolean expression applied server-side
        (SQL `WHERE`) or client-side (pandas `.query()`), depending on the
        connector. Raises `DatasetConnectionError` on failure.
        """

    # --- optional (sensible default; override when the store supports it) -

    def discover_relationships(self) -> list[dict]:
        """Foreign-key relationships `[{from_table, from_column, to_table, to_column}]`.

        Default: none (nice-to-have; never blocks import when unsupported).
        """
        return []

    # --- lifecycle no-ops (most connectors open/close per-call) -----------

    def connect(self) -> Any:
        """Open and return a connection. Default: no persistent connection is kept."""
        return None

    def close(self) -> None:
        """Close any held connection. Default: no-op."""
        return None


# type -> (module, class) registry. The connector module is imported lazily so
# each external driver stays optional (only imported when actually selected).
# Deferred engines (sqlite/mongodb/snowflake) are NOT registered in Phase 9 —
# see spec/roadmap.md "External database connectors" backlog entry.
_REGISTRY: dict[str, tuple[str, str]] = {
    "parquet": ("connectors.parquet", "ParquetConnector"),
    "postgresql": ("connectors.postgres", "PostgresConnector"),
    "postgres": ("connectors.postgres", "PostgresConnector"),  # alias
}


def get_connector(server: dict) -> DatasetConnector:
    """Return the connector for a `{type, uri}` dict.

    Dispatch is a registry lookup (no type branching); callers never know
    which concrete connector they got.

    Raises:
        DatasetConnectionError: for an unknown/unsupported `type`.
    """
    type_key = (server.get("type") or "parquet").lower()
    entry = _REGISTRY.get(type_key)
    if entry is None:
        raise DatasetConnectionError(f"Unsupported database type: {server.get('type')!r}")
    module_name, cls_name = entry
    module = importlib.import_module(module_name)
    connector_cls = getattr(module, cls_name)
    return connector_cls(server)
