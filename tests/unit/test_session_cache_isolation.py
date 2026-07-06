"""Phase 11 item 1 — per-turn session-cache isolation (C27).

`_session_load_frame` must hand every turn an isolated per-turn snapshot
(`frame.copy(deep=False)`, on BOTH the cache-hit and cache-miss return paths) —
never the cached frame object itself. Under pandas 3.x always-on Copy-on-Write
the shallow copy is a near-zero-cost lazy snapshot: an in-place mutation by one
turn's model-generated code (e.g. `df1['Date'] = pd.to_datetime(df1['Date'])`)
copies only the mutated columns and never changes what later turns of the same
session see. This was the trigger mechanism behind the 2026-07-06 chart outage
(`90b9dba` fixed only the downstream serialization symptom).

Offline unit suite: zero env, no LLM call involved, isolated SQLite via the
autouse conftest fixtures (`_isolated_db`, `_reset_node_registries` — the latter
clears `_session_cache` around every test). `_load_dataframe` reads files by
dataset id from the patched uploads dir, so no DB rows are needed here.
"""
from __future__ import annotations

import pandas as pd
import pytest

import graph.nodes as nodes_module


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    """Point the nodes' uploads dir at a tmp dir so loads read real files."""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(nodes_module, "_uploads_dir", lambda: d)
    return d


def _write_dataset(uploads_dir, dataset_id: str = "ds-iso") -> str:
    """Write a small CSV (string date column + numeric column) for `dataset_id`."""
    df = pd.DataFrame(
        {
            "d": ["2024-01-01", "2024-02-01", "2024-03-01"],
            "v": [1, 2, 3],
        }
    )
    df.to_csv(uploads_dir / f"{dataset_id}.csv", index=False)
    return dataset_id


# --------------------------------------------------------------------------- #
# (a) An in-place dtype mutation in turn 1 must NOT leak into turn 2
# --------------------------------------------------------------------------- #


def test_turn_mutation_does_not_leak_to_next_turn(uploads_dir):
    dataset_id = _write_dataset(uploads_dir)
    session_id = "sess-iso"

    # Turn 1: obtain the frame and mutate a column's dtype in place — the exact
    # trigger of the 2026-07-06 outage.
    f1 = nodes_module._session_load_frame(session_id, dataset_id)
    original_dtype = f1["d"].dtype
    f1["d"] = pd.to_datetime(f1["d"])
    assert pd.api.types.is_datetime64_any_dtype(f1["d"])  # turn 1 sees its own edit

    # Turn 2: a fresh call for the SAME session/dataset returns the ORIGINAL dtypes.
    f2 = nodes_module._session_load_frame(session_id, dataset_id)
    assert f2["d"].dtype == original_dtype
    assert not pd.api.types.is_datetime64_any_dtype(f2["d"])

    # The cached original itself stayed pristine.
    cached = nodes_module._session_cache[session_id]["frames"][dataset_id]
    assert cached["d"].dtype == original_dtype
    assert not pd.api.types.is_datetime64_any_dtype(cached["d"])


def test_turn_value_mutation_does_not_leak_to_next_turn(uploads_dir):
    """Not just dtypes — in-place VALUE edits are also confined to their turn."""
    dataset_id = _write_dataset(uploads_dir)
    session_id = "sess-iso-values"

    f1 = nodes_module._session_load_frame(session_id, dataset_id)
    f1.loc[0, "v"] = 999
    assert f1.loc[0, "v"] == 999

    f2 = nodes_module._session_load_frame(session_id, dataset_id)
    assert f2.loc[0, "v"] == 1  # the on-disk value, not turn 1's edit

    cached = nodes_module._session_cache[session_id]["frames"][dataset_id]
    assert cached.loc[0, "v"] == 1


# --------------------------------------------------------------------------- #
# (b) The returned object is never the cached object (hit AND miss paths)
# --------------------------------------------------------------------------- #


def test_returned_object_is_not_the_cached_object(uploads_dir):
    dataset_id = _write_dataset(uploads_dir)
    session_id = "sess-identity"

    # Miss path (first load).
    f1 = nodes_module._session_load_frame(session_id, dataset_id)
    cached = nodes_module._session_cache[session_id]["frames"][dataset_id]
    assert f1 is not cached

    # Hit path (second load).
    f2 = nodes_module._session_load_frame(session_id, dataset_id)
    assert f2 is not cached
    assert f2 is not f1

    # The cache keeps storing the SAME original object (membership unchanged).
    assert nodes_module._session_cache[session_id]["frames"][dataset_id] is cached


# --------------------------------------------------------------------------- #
# (c) The second call is a genuine cache HIT — no disk re-read
# --------------------------------------------------------------------------- #


def test_second_call_is_cache_hit_no_disk_reread(uploads_dir, monkeypatch):
    dataset_id = _write_dataset(uploads_dir)
    session_id = "sess-hit"

    f1 = nodes_module._session_load_frame(session_id, dataset_id)

    # Delete the underlying file AND make any further disk load blow up loudly:
    # a re-read (instead of a cache hit) cannot possibly succeed now.
    (uploads_dir / f"{dataset_id}.csv").unlink()

    def _no_reread(_dataset_id: str) -> pd.DataFrame:
        raise AssertionError("cache HIT expected — _load_dataframe must not be called")

    monkeypatch.setattr(nodes_module, "_load_dataframe", _no_reread)

    f2 = nodes_module._session_load_frame(session_id, dataset_id)
    pd.testing.assert_frame_equal(f2, f1)


# --------------------------------------------------------------------------- #
# (d) invalidate_dataset_cache behavior unchanged
# --------------------------------------------------------------------------- #


def test_invalidate_dataset_cache_behavior_unchanged(uploads_dir):
    dataset_id = _write_dataset(uploads_dir)
    session_id = "sess-inv"

    nodes_module._session_load_frame(session_id, dataset_id)
    assert dataset_id in nodes_module._session_cache[session_id]["frames"]

    nodes_module.invalidate_dataset_cache(dataset_id)

    # The entry is evicted (an emptied session entry may be dropped entirely).
    entry = nodes_module._session_cache.get(session_id)
    assert entry is None or dataset_id not in entry["frames"]

    # With the file gone too, a later load falls through to a REAL not-found —
    # never the stale frame.
    (uploads_dir / f"{dataset_id}.csv").unlink()
    with pytest.raises(FileNotFoundError):
        nodes_module._session_load_frame(session_id, dataset_id)
