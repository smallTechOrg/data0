"""The single safe-Parquet-write helper (Phase 13, Item B).

`_safe_to_parquet(df, parquet_path)` is the ONE canonical implementation of the
Phase-12 messy-sheet write discipline: attempt the Parquet write on the raw
frame FIRST for full dtype fidelity, and on the mixed-object failure class that
pyarrow rejects (`ArrowTypeError`/`ArrowInvalid` — e.g. real-world Excel title
rows that parse to `Unnamed: N` object columns holding mixed str+int), RETRY
once with a null-preserving string-coerced copy. On terminal failure the
half-written Parquet file is unlinked so no orphan survives a rolled-back write.

This helper is adopted by BOTH `upload.py`'s `_write_dataset_files` (via a
sibling slice, which delegates the Parquet half of its CSV+Parquet pair here)
and the five external Parquet-persistence sites (`api/connections.py` ×2,
`api/datasets_ops.py`, `graph/derived.py`, `api/datasets.py`). It is
self-contained — it imports NOTHING from `upload.py` (which imports FROM this
module), so a circular import is impossible. It writes the Parquet file ONLY;
callers that also keep a CSV pair write that CSV themselves and unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pyarrow import ArrowInvalid, ArrowTypeError


def _coerce_object_columns_to_string(df: pd.DataFrame) -> pd.DataFrame:
    """Return a COPY of `df` with object-dtype columns coerced to string.

    Nulls are PRESERVED: a naive `.astype(str)` would turn NaN into the literal
    string "nan", so each cell is mapped elementwise — null stays null,
    everything else becomes `str(value)`. Used ONLY for the Parquet retry in
    `_safe_to_parquet`; the caller's in-memory frame is never mutated. Mirrors
    `upload.py`'s helper of the same name (kept a local copy so this module has
    no internal imports and cannot form an import cycle).
    """
    coerced = df.copy()
    for i, dtype in enumerate(coerced.dtypes):
        if dtype == object:
            coerced.isetitem(
                i,
                coerced.iloc[:, i].map(
                    lambda v: str(v) if pd.notna(v) else None
                ),
            )
    return coerced


def _safe_to_parquet(df: pd.DataFrame, parquet_path: Path) -> None:
    """Write `df` to `parquet_path` surviving pyarrow's mixed-object rejection.

    Parquet is attempted on the raw frame FIRST so clean frames keep full dtype
    fidelity. Mixed-object columns (str+int in one object column) make pyarrow
    raise `ArrowTypeError`/`ArrowInvalid`; on that failure ONLY the write
    retries with a string-coerced COPY (nulls preserved), which reads back
    exactly what a CSV fallback would yield for those columns. If the retry also
    fails the half-written Parquet file is unlinked before re-raising so a
    rolled-back dataset never leaves an orphan behind. Always writes with
    `index=False`. Writes the Parquet file ONLY — never a CSV.
    """
    try:
        try:
            df.to_parquet(parquet_path, index=False)
        except (ArrowInvalid, ArrowTypeError):
            _coerce_object_columns_to_string(df).to_parquet(
                parquet_path, index=False
            )
    except Exception:
        try:
            parquet_path.unlink(missing_ok=True)
        except OSError:  # cleanup is best-effort — the write error wins
            pass
        raise
