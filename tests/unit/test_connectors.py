"""Offline/mocked unit tests for the C36 connector seam (`src/connectors/`).

Zero network, zero real Postgres server, zero `AGENT_GEMINI_API_KEY` — every
`psycopg2` call is mocked/faked. Covers: registry dispatch, `DatasetURI`
credential scrubbing, `PostgresConnector.connection_check` (success/failure/
timeout), `discover_tables` shape, `pull_table` row-cap behavior, and
`ParquetConnector` against the existing `datasets` table.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from connectors.base import DatasetConnectionError, get_connector
from connectors.parquet import ParquetConnector
from connectors.postgres import PostgresConnector
from connectors.uri import DatasetURI

_RAW_URI = "postgresql://scott:tiger@dbhost:5432/salesdb"


# --- DatasetURI ------------------------------------------------------------


def test_dataset_uri_display_has_no_credentials():
    uri = DatasetURI(_RAW_URI)
    display = uri.display()
    assert "tiger" not in display
    assert "scott" not in display
    assert display == "postgresql://dbhost:5432/salesdb"


def test_dataset_uri_raw_is_unchanged():
    uri = DatasetURI(_RAW_URI)
    assert uri.raw() == _RAW_URI


def test_dataset_uri_str_uses_display():
    uri = DatasetURI(_RAW_URI)
    assert "tiger" not in str(uri)
    assert str(uri) == uri.display()


def test_dataset_uri_internal_parquet_scheme():
    uri = DatasetURI("parquet:///mytable")
    assert uri.is_internal is True
    assert uri.display() == "parquet:///mytable"


# --- registry / get_connector ----------------------------------------------


def test_get_connector_dispatches_postgresql():
    connector = get_connector({"type": "postgresql", "uri": _RAW_URI})
    assert isinstance(connector, PostgresConnector)


def test_get_connector_dispatches_postgres_alias():
    connector = get_connector({"type": "postgres", "uri": _RAW_URI})
    assert isinstance(connector, PostgresConnector)


def test_get_connector_dispatches_parquet():
    connector = get_connector({"type": "parquet", "uri": "parquet:///x"})
    assert isinstance(connector, ParquetConnector)


def test_get_connector_unknown_type_raises():
    with pytest.raises(DatasetConnectionError):
        get_connector({"type": "mongodb", "uri": "mongodb://host/db"})


# --- PostgresConnector: fakes for psycopg2 ----------------------------------


class _FakeCursor:
    """Matches a query by prefix against a small script; records the last query."""

    def __init__(self, script: list[tuple[str, list[tuple]]]):
        self._script = script
        self._last_result: list[tuple] = []
        self.queries: list[str] = []

    def execute(self, query: str, params=None) -> None:
        self.queries.append(query)
        q = query.strip()
        for prefix, rows in self._script:
            if q.startswith(prefix):
                self._last_result = rows
                return
        self._last_result = []

    def fetchall(self):
        return self._last_result

    def fetchone(self):
        return self._last_result[0] if self._last_result else None


class _FakeConnection:
    def __init__(self, script: list[tuple[str, list[tuple]]]):
        self._script = script
        self.closed = False
        self.cursors: list[_FakeCursor] = []

    def cursor(self):
        c = _FakeCursor(self._script)
        self.cursors.append(c)
        return c

    def close(self):
        self.closed = True


@pytest.fixture
def fake_psycopg2(monkeypatch):
    """Patch `psycopg2.connect` to return a scripted `_FakeConnection`.

    Returns a small helper: `install(script)` sets what `.connect(...)` yields;
    `install_failure(exc)` makes `.connect(...)` raise; `install_slow(delay)`
    makes `.connect(...)` block for `delay` seconds (used for the timeout test).
    """
    import psycopg2

    state = {"conn": None}

    def _connect(*args, **kwargs):
        target = state["conn"]
        if callable(target):
            return target()
        return target

    monkeypatch.setattr(psycopg2, "connect", _connect)

    class _Installer:
        def install(self, script):
            state["conn"] = _FakeConnection(script)
            return state["conn"]

        def install_failure(self, exc: Exception):
            def _raise():
                raise exc
            state["conn"] = _raise

        def install_slow(self, delay: float, script=None):
            def _slow():
                time.sleep(delay)
                return _FakeConnection(script or [])
            state["conn"] = _slow

    return _Installer()


# --- connection_check --------------------------------------------------------


def test_connection_check_success(fake_psycopg2):
    fake_psycopg2.install([("SELECT 1", [(1,)])])
    connector = PostgresConnector({"type": "postgresql", "uri": _RAW_URI})
    connector.connection_check()  # must not raise


def test_connection_check_failure_is_credential_free(fake_psycopg2):
    fake_psycopg2.install_failure(
        Exception(f"could not connect to server: {_RAW_URI} - connection refused")
    )
    connector = PostgresConnector({"type": "postgresql", "uri": _RAW_URI})
    with pytest.raises(DatasetConnectionError) as exc_info:
        connector.connection_check()
    msg = str(exc_info.value)
    assert "tiger" not in msg
    assert "scott:tiger" not in msg
    assert _RAW_URI not in msg


def test_connection_check_timeout_is_credential_free(monkeypatch, fake_psycopg2):
    import connectors.postgres as postgres_module

    monkeypatch.setattr(postgres_module, "_CONNECT_TIMEOUT_SECONDS", 0.05)
    fake_psycopg2.install_slow(0.3)
    connector = PostgresConnector({"type": "postgresql", "uri": _RAW_URI})
    with pytest.raises(DatasetConnectionError) as exc_info:
        connector.connection_check()
    msg = str(exc_info.value)
    assert "timed out" in msg.lower()
    assert "tiger" not in msg
    assert _RAW_URI not in msg


# --- discover_tables ----------------------------------------------------------


def test_discover_tables_shape(fake_psycopg2):
    fake_psycopg2.install(
        [
            ("SELECT table_name FROM information_schema.tables", [("orders",)]),
            (
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns",
                [("id", "integer", "NO"), ("total", "numeric", "YES")],
            ),
        ]
    )
    connector = PostgresConnector({"type": "postgresql", "uri": _RAW_URI})
    tables = connector.discover_tables()
    assert tables == [
        {
            "table_name": "orders",
            "column_names": ["id", "total"],
            "schema": [
                {"name": "id", "dtype": "integer", "nullable": False},
                {"name": "total", "dtype": "numeric", "nullable": True},
            ],
            "row_count": None,
        }
    ]


def test_discover_relationships_swallows_failure(fake_psycopg2):
    fake_psycopg2.install_failure(Exception("relation info_schema unavailable"))
    connector = PostgresConnector({"type": "postgresql", "uri": _RAW_URI})
    assert connector.discover_relationships() == []


# --- pull_table -----------------------------------------------------------


def test_pull_table_uses_row_cap_limit(fake_psycopg2, monkeypatch):
    import connectors.postgres as postgres_module

    fake_psycopg2.install([])
    captured = {}

    def _fake_read_sql(query, conn):
        captured["query"] = query
        return pd.DataFrame({"id": [1, 2, 3]})

    monkeypatch.setattr(postgres_module.pd, "read_sql", _fake_read_sql)
    connector = PostgresConnector({"type": "postgresql", "uri": _RAW_URI})
    df = connector.pull_table("orders")
    assert isinstance(df, pd.DataFrame)
    assert "LIMIT 500000" in captured["query"]
    assert '"orders"' in captured["query"]


def test_pull_table_applies_filter(fake_psycopg2, monkeypatch):
    import connectors.postgres as postgres_module

    fake_psycopg2.install([])
    captured = {}

    def _fake_read_sql(query, conn):
        captured["query"] = query
        return pd.DataFrame({"id": [1]})

    monkeypatch.setattr(postgres_module.pd, "read_sql", _fake_read_sql)
    connector = PostgresConnector({"type": "postgresql", "uri": _RAW_URI})
    connector.pull_table("orders", filter="created_at > '2026-01-01'")
    assert "WHERE created_at > '2026-01-01'" in captured["query"]


# --- ParquetConnector (internal, wraps the existing `datasets` table) ------


def test_parquet_connector_discover_and_pull(tmp_path):
    from db.models import DatasetRow
    from db.session import create_db_session

    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    parquet_path = tmp_path / "sample.parquet"
    df.to_parquet(parquet_path, index=False)

    with create_db_session() as session:
        row = DatasetRow(
            filename="my_table",
            file_path=str(parquet_path),
            parquet_path=str(parquet_path),
            row_count=3,
            col_count=2,
            columns_json=[{"name": "a", "dtype": "int64"}, {"name": "b", "dtype": "object"}],
            content_hash="deadbeef",
            format="csv",
            origin="uploaded",
        )
        session.add(row)

    connector = ParquetConnector({"type": "parquet", "uri": "parquet:///my_table"})
    connector.connection_check()  # must not raise; no network involved

    tables = connector.discover_tables()
    match = next(t for t in tables if t["table_name"] == "my_table")
    assert match["column_names"] == ["a", "b"]
    assert match["row_count"] == 3

    pulled = connector.pull_table("my_table")
    assert isinstance(pulled, pd.DataFrame)
    assert list(pulled.columns) == ["a", "b"]
    assert len(pulled) == 3


def test_parquet_connector_pull_unknown_table_raises(tmp_path):
    connector = ParquetConnector({"type": "parquet", "uri": "parquet:///nope"})
    with pytest.raises(DatasetConnectionError):
        connector.pull_table("does_not_exist")
