"""Offline API suite for `/connections/*` (C36, Phase 9).

In-memory SQLite (`api_client` fixture) + a fake connector monkeypatched onto
`api.connections.get_connector` — zero real Postgres server, zero
`AGENT_GEMINI_API_KEY` (this capability makes no LLM calls at all). Covers the
`403 connectors_disabled` gate, the `POST /connections/import` per-table
partial-failure shape, and the `resync` 400/404 paths, plus a credential-
hygiene grep of every response body.
"""
from __future__ import annotations

import io

import pandas as pd
import pytest

from connectors.base import DatasetConnectionError

_RAW_URI = "postgresql://scott:tiger@dbhost:5432/salesdb"


def _enable_connectors(monkeypatch):
    monkeypatch.setenv("AGENT_ENABLE_DB_CONNECTORS", "true")
    import config.settings as m
    m._settings = None


class _FakeConnector:
    """A stand-in for `PostgresConnector` — no `psycopg2`/network involved."""

    def __init__(self, tables=None, relationships=None, fail_check=False, pull_map=None):
        self._tables = tables or []
        self._relationships = relationships or []
        self._fail_check = fail_check
        self._pull_map = pull_map or {}
        self.closed = False

    def connection_check(self):
        if self._fail_check:
            raise DatasetConnectionError("Could not connect to postgresql://dbhost:5432/salesdb: refused")

    def discover_tables(self):
        return self._tables

    def discover_relationships(self):
        return self._relationships

    def pull_table(self, table_name, filter=None):
        entry = self._pull_map.get(table_name)
        if isinstance(entry, Exception):
            raise entry
        if entry is not None:
            return entry
        return pd.DataFrame({"id": [1, 2], "total": [10.0, 20.0]})

    def close(self):
        self.closed = True


# --- GET /connections/status -------------------------------------------------


def test_status_reports_disabled_by_default(api_client):
    r = api_client.get("/connections/status")
    assert r.status_code == 200
    assert r.json()["data"] == {"enabled": False}


def test_status_reports_enabled_when_flag_set(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    r = api_client.get("/connections/status")
    assert r.status_code == 200
    assert r.json()["data"] == {"enabled": True}


# --- 403 gate (flag off) -----------------------------------------------------


def test_check_403_when_disabled(api_client):
    r = api_client.post(
        "/connections/check", json={"type": "postgresql", "uri": _RAW_URI}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "connectors_disabled"


def test_import_403_when_disabled(api_client):
    r = api_client.post(
        "/connections/import",
        json={"type": "postgresql", "uri": _RAW_URI, "tables": [{"table_name": "orders"}]},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "connectors_disabled"


def test_resync_403_when_disabled(api_client):
    r = api_client.post("/connections/some-id/resync")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "connectors_disabled"


# --- POST /connections/check --------------------------------------------------


def test_check_success_returns_tables_and_relationships(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    fake = _FakeConnector(
        tables=[
            {
                "table_name": "orders",
                "column_names": ["id", "total"],
                "schema": [{"name": "id", "dtype": "integer", "nullable": False}],
                "row_count": None,
            }
        ],
        relationships=[
            {"from_table": "orders", "from_column": "customer_id", "to_table": "customers", "to_column": "id"}
        ],
    )
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake)

    r = api_client.post("/connections/check", json={"type": "postgresql", "uri": _RAW_URI})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["tables"][0]["table_name"] == "orders"
    assert data["relationships"][0]["from_table"] == "orders"
    assert fake.closed is True
    # Credential hygiene: the raw URI/password never appears in the response.
    assert "tiger" not in r.text
    assert _RAW_URI not in r.text


def test_check_connection_failure_returns_400(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    fake = _FakeConnector(fail_check=True)
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake)

    r = api_client.post("/connections/check", json={"type": "postgresql", "uri": _RAW_URI})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "connection_failed"
    assert "tiger" not in r.text
    assert fake.closed is True


def test_check_unsupported_type_returns_400(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    r = api_client.post("/connections/check", json={"type": "mongodb", "uri": "mongodb://h/db"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "unsupported_type"


# --- POST /connections/import -------------------------------------------------


def test_import_partial_failure_shape(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    fake = _FakeConnector(
        pull_map={
            "orders": pd.DataFrame({"id": [1, 2], "total": [10.0, 20.0]}),
            "bad_view": DatasetConnectionError("permission denied for view bad_view"),
        }
    )
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake)

    body = {
        "type": "postgresql",
        "uri": _RAW_URI,
        "tables": [{"table_name": "orders"}, {"table_name": "bad_view"}],
    }
    r = api_client.post("/connections/import", json=body)
    assert r.status_code == 200, r.text
    results = r.json()["data"]["results"]
    assert len(results) == 2

    ok_result = next(x for x in results if x["table_name"] == "orders")
    err_result = next(x for x in results if x["table_name"] == "bad_view")
    assert ok_result["status"] == "ok"
    assert "dataset_id" in ok_result
    assert err_result["status"] == "error"
    assert "permission denied" in err_result["message"]
    assert "tiger" not in r.text

    # The successful table registered as a real dataset row, origin="connected".
    get_r = api_client.get(f"/datasets/{ok_result['dataset_id']}")
    assert get_r.status_code == 200
    dataset = get_r.json()["data"]
    assert dataset["origin"] == "connected"
    assert dataset["row_count"] == 2
    assert dataset["col_count"] == 2
    assert "source_uri_raw" not in dataset


def test_import_connection_failure_attempts_no_tables(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    fake = _FakeConnector(fail_check=True)
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake)

    body = {"type": "postgresql", "uri": _RAW_URI, "tables": [{"table_name": "orders"}]}
    r = api_client.post("/connections/import", json=body)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "connection_failed"


def test_import_empty_tables_returns_400(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    body = {"type": "postgresql", "uri": _RAW_URI, "tables": []}
    r = api_client.post("/connections/import", json=body)
    assert r.status_code == 400


# --- POST /connections/{id}/resync --------------------------------------------


def test_resync_404_when_dataset_missing(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    r = api_client.post("/connections/does-not-exist/resync")
    assert r.status_code == 404


def test_resync_400_when_dataset_not_connected(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    files = {"file": ("sample.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    up = api_client.post("/upload", files=files)
    assert up.status_code == 200
    dataset_id = up.json()["data"]["dataset_id"]

    r = api_client.post(f"/connections/{dataset_id}/resync")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "not_connected"


def test_resync_success_updates_counts(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    fake_import = _FakeConnector(pull_map={"orders": pd.DataFrame({"id": [1, 2]})})
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake_import)

    body = {"type": "postgresql", "uri": _RAW_URI, "tables": [{"table_name": "orders"}]}
    imp = api_client.post("/connections/import", json=body)
    assert imp.status_code == 200, imp.text
    dataset_id = imp.json()["data"]["results"][0]["dataset_id"]

    fake_resync = _FakeConnector(pull_map={"orders": pd.DataFrame({"id": [1, 2, 3]})})
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake_resync)

    r = api_client.post(f"/connections/{dataset_id}/resync")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["row_count"] == 3
    assert data["source_type"] == "postgresql"
    assert "source_uri_raw" not in data
    assert "tiger" not in r.text


def test_resync_error_when_pull_fails(api_client, monkeypatch):
    _enable_connectors(monkeypatch)
    fake_import = _FakeConnector(pull_map={"orders": pd.DataFrame({"id": [1, 2]})})
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake_import)

    body = {"type": "postgresql", "uri": _RAW_URI, "tables": [{"table_name": "orders"}]}
    imp = api_client.post("/connections/import", json=body)
    dataset_id = imp.json()["data"]["results"][0]["dataset_id"]

    fake_failing = _FakeConnector(pull_map={"orders": DatasetConnectionError("connection reset")})
    monkeypatch.setattr("api.connections.get_connector", lambda server: fake_failing)

    r = api_client.post(f"/connections/{dataset_id}/resync")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "resync_error"
