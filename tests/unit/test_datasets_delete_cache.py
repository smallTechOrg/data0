"""Regression coverage for C27: deleting a dataset must invalidate the in-memory
session DataFrame cache (`graph.nodes._session_cache`).

Before this fix, `DELETE /datasets/{id}` and `DELETE /datasets` removed the on-disk
files + DB row but left any session's cached DataFrame in place — a session that
had already loaded the dataset (via `_session_load_frame`) kept serving the stale,
deleted data instead of falling through to a real "not found" on the next turn.

`clean`/`apply` (api/datasets_ops.py) and re-derive (api/datasets.py + graph/derived.py)
already call `invalidate_dataset_cache` after mutating a dataset; this suite covers
the delete paths, which had no such call.

Offline unit suite: stub provider (irrelevant here — no LLM call involved), isolated
SQLite (conftest `_isolated_db`), zero network. Directly exercises `_session_load_frame`
/ `_session_cache` from `graph.nodes` alongside the FastAPI delete routes.
"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch):
    """Pin the offline stub provider regardless of any key present in `.env`."""
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "stub")
    import config.settings as m
    m._settings = None


@pytest.fixture
def datasets_client(_isolated_db, tmp_path, monkeypatch):
    """A TestClient over a minimal app mounting ONLY the datasets router, with
    nodes'/derived's uploads dir pointed at a tmp dir so file lookups are real."""
    import graph.derived as derived_module
    import graph.nodes as nodes_module
    from api.datasets import router

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: uploads)
    monkeypatch.setattr(derived_module, "_uploads_dir", lambda: uploads)

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, uploads


@pytest.fixture
def make_dataset():
    """Create a dataset row + on-disk CSV/Parquet under the given uploads dir."""
    from db.models import DatasetRow
    from db.session import create_db_session

    def _make(uploads_dir, df: pd.DataFrame, filename: str = "data.csv") -> str:
        with create_db_session() as session:
            row = DatasetRow(
                filename=filename,
                file_path="",
                row_count=len(df),
                col_count=len(df.columns),
                columns_json=[{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
                content_hash=f"hash-{filename}",
                format="csv",
                origin="uploaded",
            )
            session.add(row)
            session.flush()
            dataset_id = row.id
            csv_path = uploads_dir / f"{dataset_id}.csv"
            parquet_path = uploads_dir / f"{dataset_id}.parquet"
            df.to_csv(csv_path, index=False)
            df.to_parquet(parquet_path, index=False)
            row.file_path = str(csv_path)
            row.parquet_path = str(parquet_path)
        return dataset_id

    return _make


def test_delete_dataset_invalidates_session_cache(datasets_client, make_dataset):
    """Repro: a session loads dataset X into `_session_cache`, then X is deleted via
    `DELETE /datasets/{id}` — the cache entry for X must be evicted so a later
    `_session_load_frame` call falls through to a real "not found" (FileNotFoundError)
    instead of returning the stale, deleted DataFrame."""
    from graph import nodes as nodes_module

    client, uploads = datasets_client
    ds_id = make_dataset(uploads, pd.DataFrame({"a": [1, 2, 3]}))

    session_id = "sess-1"
    # Agent loads dataset X into the session cache (simulates a prior turn).
    loaded = nodes_module._session_load_frame(session_id, ds_id)
    assert list(loaded["a"]) == [1, 2, 3]
    assert ds_id in nodes_module._session_cache[session_id]["frames"]

    r = client.delete(f"/datasets/{ds_id}")
    assert r.status_code == 200, r.text

    # The cache entry for the deleted dataset must be gone.
    entry = nodes_module._session_cache.get(session_id)
    if entry is not None:
        assert ds_id not in entry["frames"]

    # A subsequent load in the SAME session must NOT return the stale frame — the
    # on-disk files are gone too, so it now raises a real "not found" error.
    with pytest.raises(FileNotFoundError):
        nodes_module._session_load_frame(session_id, ds_id)


def test_delete_dataset_cascade_invalidates_derived_child_cache(datasets_client, make_dataset):
    """A derived child dataset loaded into the session cache is also evicted when its
    parent is deleted (C15 cascade + C27 invalidation together)."""
    from db.models import DatasetRow
    from db.session import create_db_session
    from graph import nodes as nodes_module

    client, uploads = datasets_client
    parent_id = make_dataset(uploads, pd.DataFrame({"a": [1, 2, 3]}), filename="parent.csv")

    # Register a derived child of parent_id (mirrors save_dataset's registration).
    child_df = pd.DataFrame({"a": [1, 2]})
    with create_db_session() as session:
        child = DatasetRow(
            filename="child.csv",
            file_path="",
            row_count=len(child_df),
            col_count=len(child_df.columns),
            columns_json=[{"name": "a", "dtype": "int64"}],
            content_hash="hash-child",
            format="csv",
            origin="derived",
            derived_from_dataset_ids=[parent_id],
        )
        session.add(child)
        session.flush()
        child_id = child.id
        csv_path = uploads / f"{child_id}.csv"
        parquet_path = uploads / f"{child_id}.parquet"
        child_df.to_csv(csv_path, index=False)
        child_df.to_parquet(parquet_path, index=False)
        child.file_path = str(csv_path)
        child.parquet_path = str(parquet_path)

    session_id = "sess-2"
    nodes_module._session_load_frame(session_id, parent_id)
    nodes_module._session_load_frame(session_id, child_id)
    assert child_id in nodes_module._session_cache[session_id]["frames"]

    r = client.delete(f"/datasets/{parent_id}")
    assert r.status_code == 200, r.text
    assert child_id in r.json()["data"]["derived_deleted"]

    entry = nodes_module._session_cache.get(session_id)
    if entry is not None:
        assert child_id not in entry["frames"]
        assert parent_id not in entry["frames"]

    with pytest.raises(FileNotFoundError):
        nodes_module._session_load_frame(session_id, child_id)


def test_delete_all_datasets_invalidates_session_cache(datasets_client, make_dataset):
    """`DELETE /datasets` (delete-all) must invalidate EVERY deleted dataset's cache
    entry, not just leave stale frames behind for datasets that were never touched
    by the single-delete path."""
    from graph import nodes as nodes_module

    client, uploads = datasets_client
    ds1 = make_dataset(uploads, pd.DataFrame({"a": [1]}), filename="one.csv")
    ds2 = make_dataset(uploads, pd.DataFrame({"b": [2]}), filename="two.csv")

    session_id = "sess-3"
    nodes_module._session_load_frame(session_id, ds1)
    nodes_module._session_load_frame(session_id, ds2)
    assert set(nodes_module._session_cache[session_id]["frames"]) == {ds1, ds2}

    r = client.delete("/datasets")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deleted_count"] == 2

    # Both cache entries must be gone (empty session entry may be dropped entirely).
    entry = nodes_module._session_cache.get(session_id)
    if entry is not None:
        assert ds1 not in entry["frames"]
        assert ds2 not in entry["frames"]

    with pytest.raises(FileNotFoundError):
        nodes_module._session_load_frame(session_id, ds1)
    with pytest.raises(FileNotFoundError):
        nodes_module._session_load_frame(session_id, ds2)
