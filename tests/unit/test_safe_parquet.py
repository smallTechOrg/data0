"""Offline regression suite for the shared safe-Parquet-write helper (Phase 13,
Item B).

`_safe_to_parquet` is the ONE canonical implementation of the Phase-12
messy-sheet write discipline (parquet-first for dtype fidelity; retry on
pyarrow's mixed-object rejection with a null-preserving string-coerced copy;
unlink the orphan on terminal failure). These tests prove:

1. it SUCCEEDS on a mixed-object frame that a raw `df.to_parquet` REJECTS with
   `ArrowTypeError`/`ArrowInvalid`, and that nulls survive the coercion;
2. a clean frame keeps full dtype fidelity (parquet-first, no coercion);
3. a terminal failure (retry also raises) leaves no orphan Parquet file;
4. all five external persistence sites route through this one helper.

Zero env, zero network, zero LLM calls — pure offline unit coverage.
"""
import pandas as pd
import pytest
from pyarrow import ArrowInvalid, ArrowTypeError

from api._parquet import _safe_to_parquet


def _mixed_object_frame() -> pd.DataFrame:
    """A frame whose object column holds mixed str+int+null.

    This mirrors real-world Excel title rows that parse to `Unnamed: N` object
    columns; pyarrow infers the column as string and then rejects the int.
    """
    return pd.DataFrame(
        {
            "mixed": pd.Series(["alpha", 7, None, "beta"], dtype=object),
            "clean": [1, 2, 3, 4],
        }
    )


def test_raw_to_parquet_rejects_mixed_object_frame(tmp_path):
    """Guard: the raw write DOES raise on the mixed frame (proves the fixture
    actually exercises the failure class the helper exists to survive)."""
    df = _mixed_object_frame()
    with pytest.raises((ArrowInvalid, ArrowTypeError)):
        df.to_parquet(tmp_path / "raw.parquet", index=False)


def test_safe_to_parquet_survives_mixed_frame_preserving_nulls(tmp_path):
    """The helper writes the file and nulls survive the string coercion."""
    df = _mixed_object_frame()
    path = tmp_path / "safe.parquet"

    _safe_to_parquet(df, path)

    assert path.exists()
    reloaded = pd.read_parquet(path)
    # Mixed column coerced to string, NULL PRESERVED (not the literal "nan").
    assert reloaded["mixed"].isna().tolist() == [False, False, True, False]
    assert reloaded["mixed"].dropna().tolist() == ["alpha", "7", "beta"]
    # The clean numeric column is untouched.
    assert reloaded["clean"].tolist() == [1, 2, 3, 4]


def test_safe_to_parquet_preserves_dtype_for_clean_frame(tmp_path):
    """Parquet-first: a clean frame keeps full dtype fidelity (no coercion)."""
    df = pd.DataFrame({"n": [1, 2, 3], "f": [1.5, 2.5, 3.5], "s": ["a", "b", "c"]})
    path = tmp_path / "clean.parquet"

    _safe_to_parquet(df, path)

    reloaded = pd.read_parquet(path)
    assert reloaded["n"].dtype == df["n"].dtype
    assert reloaded["f"].dtype == df["f"].dtype
    assert reloaded.equals(df)


def test_safe_to_parquet_unlinks_orphan_on_terminal_failure(tmp_path, monkeypatch):
    """When BOTH the raw write and the coerced retry fail, no orphan survives."""
    import api._parquet as parquet_module

    df = _mixed_object_frame()  # forces the ArrowTypeError → retry path
    path = tmp_path / "orphan.parquet"
    path.write_bytes(b"half-written")  # simulate a partial write to be cleaned

    def _boom(_df):
        raise RuntimeError("coerce blew up")

    monkeypatch.setattr(parquet_module, "_coerce_object_columns_to_string", _boom)

    with pytest.raises(RuntimeError, match="coerce blew up"):
        _safe_to_parquet(df, path)

    assert not path.exists()  # orphan removed, re-raised the original error


def test_api_modules_bind_the_shared_helper():
    """The three api-package modules import the ONE canonical helper top-level.

    connections.py holds TWO call sites (snapshot pull + re-sync) sharing this
    binding; datasets_ops.py and datasets.py hold one each.
    """
    import api._parquet as canonical
    from api import connections, datasets, datasets_ops

    for module in (connections, datasets, datasets_ops):
        assert module._safe_to_parquet is canonical._safe_to_parquet


def test_all_five_sites_call_the_helper_and_no_raw_writes_remain():
    """Source-level guard: every swapped site calls `_safe_to_parquet` and none
    of the five files still writes Parquet raw.

    `graph/derived.py` imports the helper deferred (inside the function) to
    dodge the `api/__init__` create-app import cycle, so it is checked by source
    rather than a module-level binding.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    # (relative source path, expected number of `_safe_to_parquet(` call sites)
    sites = {
        "api/connections.py": 2,
        "api/datasets_ops.py": 1,
        "graph/derived.py": 1,
        "api/datasets.py": 1,
    }
    for rel, expected_calls in sites.items():
        text = (src / rel).read_text(encoding="utf-8")
        assert text.count("_safe_to_parquet(") == expected_calls, rel
        # No raw `.to_parquet(` write survives at any swapped site.
        assert ".to_parquet(" not in text, rel
