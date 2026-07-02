"""Optional live-Postgres integration test for C36 (Phase 9).

Skipped gracefully unless `TEST_POSTGRES_URI` is set in the environment — the
gate never depends on a real Postgres server being available. When set, it
exercises `PostgresConnector` against a real database end to end:
`connection_check()` succeeds, `discover_tables()` finds at least one table,
and `POST /connections/import` registers it as a real `datasets` row.

Set `TEST_POSTGRES_URI=postgresql://user:pass@host:5432/db` (a database with
at least one readable table) to run this test locally.
"""
from __future__ import annotations

import os

import pytest

_TEST_POSTGRES_URI = os.environ.get("TEST_POSTGRES_URI")

pytestmark = pytest.mark.skipif(
    not _TEST_POSTGRES_URI,
    reason="TEST_POSTGRES_URI not set — optional live-Postgres connector test skipped",
)


def _enable_connectors(monkeypatch):
    monkeypatch.setenv("AGENT_ENABLE_DB_CONNECTORS", "true")
    import config.settings as m
    m._settings = None


def test_connection_check_against_real_postgres():
    from connectors.postgres import PostgresConnector

    connector = PostgresConnector({"type": "postgresql", "uri": _TEST_POSTGRES_URI})
    try:
        connector.connection_check()  # must not raise
    finally:
        connector.close()


def test_discover_tables_finds_at_least_one_table():
    from connectors.postgres import PostgresConnector

    connector = PostgresConnector({"type": "postgresql", "uri": _TEST_POSTGRES_URI})
    try:
        tables = connector.discover_tables()
        assert len(tables) >= 1
    finally:
        connector.close()


def test_import_registers_a_real_dataset_row(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    from connectors.postgres import PostgresConnector

    connector = PostgresConnector({"type": "postgresql", "uri": _TEST_POSTGRES_URI})
    try:
        tables = connector.discover_tables()
    finally:
        connector.close()
    assert tables, "the TEST_POSTGRES_URI database must have at least one table"
    table_name = tables[0]["table_name"]

    r = api_client.post(
        "/connections/import",
        json={
            "type": "postgresql",
            "uri": _TEST_POSTGRES_URI,
            "tables": [{"table_name": table_name}],
        },
    )
    assert r.status_code == 200, r.text
    result = r.json()["data"]["results"][0]
    assert result["status"] == "ok"
    dataset_id = result["dataset_id"]

    get_r = api_client.get(f"/datasets/{dataset_id}")
    assert get_r.status_code == 200
    assert get_r.json()["data"]["origin"] == "connected"
