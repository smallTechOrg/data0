"""Offline unit tests for the dashboard data profile (C40, Phase 15)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from graph.dashboard_profile import (
    MAX_CELL_CHARS,
    MAX_PROFILED_COLUMNS,
    PROFILE_TEXT_BUDGET,
    columns_schema_for,
    profile_dataframe,
)


def _mixed_df(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    return pd.DataFrame(
        {
            "order_id": np.arange(n),
            "region": rng.choice(["N", "S", "E", "W"], n),
            "amount": rng.normal(100, 20, n).round(2),
            "order_date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "ship_date": [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-02-01", periods=n)],
            "notes": ["x" * 60 + str(i) for i in range(n)],
            "flag": rng.choice([True, False], n),
            "rating": rng.integers(1, 6, n),
        }
    )


def _roles(profile) -> dict[str, str]:
    return {c["name"]: c["role"] for c in profile["columns"]}


def test_roles_on_mixed_dtype_fixture():
    p = profile_dataframe(_mixed_df())
    roles = _roles(p)
    assert roles["order_id"] == "id"
    assert roles["region"] == "dimension"
    assert roles["amount"] == "measure"
    assert roles["order_date"] == "time"
    assert roles["notes"] == "text"
    assert roles["flag"] == "dimension"
    assert roles["rating"] == "dimension"  # low-cardinality integer


def test_date_like_text_is_detected_as_time():
    p = profile_dataframe(_mixed_df())
    assert _roles(p)["ship_date"] == "time"
    assert p["columns_schema"]["ship_date"] == "datetime"
    assert p["columns_schema"]["amount"] == "float"
    assert p["columns_schema"]["rating"] == "integer"
    assert p["columns_schema"]["flag"] == "boolean"
    assert p["columns_schema"]["region"] == "text"


def test_stats_are_computed_over_the_full_frame():
    df = _mixed_df(500)
    p = profile_dataframe(df)
    amt = next(c for c in p["columns"] if c["name"] == "amount")
    assert abs(amt["stats"]["sum"] - df["amount"].sum()) < 1e-2
    region = next(c for c in p["columns"] if c["name"] == "region")
    assert sum(n for _, n in region["stats"]["top"]) <= 500
    assert region["nunique"] == 4


def test_column_cap_and_budget():
    df = pd.DataFrame({f"col_{i}": np.arange(30) * i for i in range(90)})
    p = profile_dataframe(df)
    assert len(p["columns"]) == MAX_PROFILED_COLUMNS
    assert len(p["other_columns"]) == 90 - MAX_PROFILED_COLUMNS
    # every column (even the unprofiled ones) is still known to the validator
    assert set(p["columns_schema"]) == set(df.columns)
    assert len(p["text"]) <= PROFILE_TEXT_BUDGET
    assert "columns" in json.loads(p["text"]) or len(p["text"]) == PROFILE_TEXT_BUDGET


def test_sample_cells_truncated_and_limited():
    p = profile_dataframe(_mixed_df())
    assert 1 <= len(p["sample_rows"]) <= 5
    for row in p["sample_rows"]:
        assert all(len(v) <= MAX_CELL_CHARS for v in row.values())
    assert len(p["text"]) <= PROFILE_TEXT_BUDGET


def test_profile_text_is_valid_compact_json():
    p = profile_dataframe(_mixed_df(), notes="orders of 2024")
    data = json.loads(p["text"])
    assert data["rows"] == 200
    names = [c["name"] for c in data["columns"]]
    assert "amount" in names


def test_columns_schema_for_matches_profile():
    df = _mixed_df()
    assert columns_schema_for(df) == profile_dataframe(df)["columns_schema"]


def test_empty_and_null_heavy_columns_do_not_crash():
    df = pd.DataFrame({"a": [None, None, None], "b": [1, 2, 3]})
    p = profile_dataframe(df)
    assert {c["name"] for c in p["columns"]} == {"a", "b"}
