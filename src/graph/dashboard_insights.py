"""Dataset-type detection, data overview and fact-based insights for dashboards.

Everything here is deterministic pandas: no LLM, no invented causes. Each insight
states only what the numbers show (leader and share, change over time, peak,
data-quality issues). Never raises — a failing check is simply skipped.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as pdt

from graph.dashboard_data import (
    _agg_by,
    _auto_grain,
    _bucket,
    _bucket_label,
    _is_datetime_like,
    _to_datetime,
    apply_filters,
    widget_fields,
)

MAX_AI_INSIGHTS = 8

# key -> (label, keywords matched against column-name tokens, what such dashboards focus on)
_DOMAINS: dict[str, tuple[str, set[str], str]] = {
    "sales": (
        "Sales",
        {"sales", "revenue", "order", "orders", "product", "customer", "quantity", "qty", "units",
         "discount", "price", "region", "invoice", "profit", "category", "salesperson"},
        "revenue, orders, average order value, best-selling products, regional split and monthly trend",
    ),
    "stock_market": (
        "Stock market",
        {"open", "high", "low", "close", "adj", "volume", "ticker", "symbol", "stock", "dividend",
         "shares", "portfolio", "return", "returns", "nav", "exchange"},
        "price trend, returns, volatility, volume, top gainers and losers, portfolio value",
    ),
    "hr": (
        "HR",
        {"employee", "employees", "salary", "department", "attrition", "hire", "hired", "tenure",
         "designation", "manager", "gender", "performance", "leave", "headcount", "age", "job",
         "joining", "experience"},
        "headcount, attrition, department mix, salary distribution and tenure",
    ),
    "finance": (
        "Finance",
        {"income", "expense", "expenses", "profit", "budget", "balance", "debit", "credit",
         "transaction", "account", "cash", "amount", "ledger", "tax", "loss", "payable",
         "receivable", "cost", "margin"},
        "income vs expenses, profit, budget utilisation and monthly cash flow",
    ),
    "ecommerce": (
        "E-commerce",
        {"cart", "sku", "conversion", "session", "sessions", "returns", "shipping", "checkout",
         "coupon", "customer", "order", "visitors", "clicks", "refund", "delivery", "rating"},
        "customers, orders, conversion, product performance and returns",
    ),
}

_TOKEN_RE = re.compile(r"[A-Za-z]+")


def _tokens(name: Any) -> set[str]:
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name))
    return {t.lower() for t in _TOKEN_RE.findall(spaced)}


def detect_domain(df: pd.DataFrame) -> dict[str, Any]:
    """Guess the dataset type from its column names. Falls back to `general`."""
    cols: set[str] = set()
    for c in df.columns:
        cols |= _tokens(c)
    scores: dict[str, list[str]] = {}
    for key, (_label, words, _focus) in _DOMAINS.items():
        hit = sorted(words & cols)
        if hit:
            scores[key] = hit
    # Stock data is only credible with price-style columns.
    if "stock_market" in scores and len({"open", "high", "low", "close"} & cols) < 2 and not (
        {"ticker", "symbol", "stock", "portfolio"} & cols
    ):
        scores.pop("stock_market")
    if not scores:
        return {"key": "general", "label": "General", "confidence": 0.0, "matched": [],
                "focus": "an overview of the key measures, categories and trends"}
    best = max(scores, key=lambda k: (len(scores[k]), k == "ecommerce"))
    n = len(scores[best])
    if n < 2:
        return {"key": "general", "label": "General", "confidence": 0.0, "matched": [],
                "focus": "an overview of the key measures, categories and trends"}
    label, words, focus = _DOMAINS[best]
    return {
        "key": best,
        "label": label,
        "confidence": round(min(1.0, n / 5), 2),
        "matched": scores[best][:6],
        "focus": focus,
    }


def domain_hint(domain: dict[str, Any]) -> str:
    if domain.get("key") == "general":
        return ""
    return (
        f"This looks like a {domain['label']} dataset; a good dashboard for it focuses on "
        f"{domain['focus']} (use only columns that exist)."
    )


def overview(df: pd.DataFrame) -> dict[str, Any]:
    rows, cols = int(len(df)), int(len(df.columns))
    cells = rows * cols
    missing = int(df.isna().sum().sum()) if cells else 0
    try:
        dupes = int(df.duplicated().sum())
    except Exception:  # noqa: BLE001 — unhashable cell values
        dupes = 0
    return {
        "rows": rows,
        "columns": cols,
        "missing_cells": missing,
        "completeness": round(100 * (1 - missing / cells), 1) if cells else 100.0,
        "duplicate_rows": dupes,
    }


def _num(v: float) -> str:
    v = float(v)
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if a >= 1e4:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


def _measure_name(y: dict[str, Any]) -> str:
    return "count of rows" if y.get("field") is None else f"{y['agg']} of {y['field']}"


def _chart_insights(df: pd.DataFrame, w: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = w["chart"]
    ctype, x, y = cfg["type"], cfg.get("x"), cfg.get("y") or {}
    if ctype not in ("bar", "pie", "line", "area") or x not in df.columns:
        return []
    frame = apply_filters(df, w.get("filters"))
    if len(frame) == 0:
        return []
    xs = frame[x]
    time_axis = ctype in ("line", "area", "bar") and _is_datetime_like(xs)
    grain = None
    if time_axis:
        ts = _to_datetime(xs)
        grain = cfg.get("time_grain") or _auto_grain(ts)
        key = _bucket(ts, grain)
    else:
        key = xs
    base = _agg_by(frame.assign(__key=key.values), ["__key"], y).dropna()
    if len(base) < 2:
        return []
    measure = _measure_name(y)
    out: list[dict[str, Any]] = []

    if time_axis:
        base = base.sort_index()
        first, last = float(base.iloc[0]), float(base.iloc[-1])
        lab = lambda i: _bucket_label(base.index[i], grain)  # noqa: E731
        partial = " The latest period may be incomplete." if grain in ("month", "quarter", "year") else ""
        if first != 0:
            pct = (last - first) / abs(first) * 100
            if abs(pct) >= 1:
                word = "rose" if pct > 0 else "fell"
                out.append({
                    "kind": "trend", "tone": "positive" if pct > 0 else "negative", "widget_id": w["id"],
                    "text": f"{w['title']}: {measure} {word} {abs(pct):.1f}% from {lab(0)} ({_num(first)}) to {lab(-1)} ({_num(last)}).{partial}",
                })
            else:
                out.append({"kind": "trend", "tone": "neutral", "widget_id": w["id"],
                            "text": f"{w['title']}: {measure} stayed flat between {lab(0)} and {lab(-1)}."})
        pk, lo = int(np.argmax(base.to_numpy(dtype=float))), int(np.argmin(base.to_numpy(dtype=float)))
        out.append({"kind": "peak", "tone": "neutral", "widget_id": w["id"],
                    "text": f"Highest {grain or 'period'} is {lab(pk)} ({_num(base.iloc[pk])}); lowest is {lab(lo)} ({_num(base.iloc[lo])})."})
        return out

    if y.get("agg") in ("sum", "count", None) or y.get("field") is None:
        total = float(base.sum())
        if total > 0 and (base >= 0).all():
            ranked = base.sort_values(ascending=False)
            top = ranked.index[0]
            share = float(ranked.iloc[0]) / total * 100
            msg = f"{w['title']}: {top} leads with {share:.0f}% of the total ({_num(ranked.iloc[0])})."
            if len(ranked) >= 3:
                top3 = float(ranked.iloc[:3].sum()) / total * 100
                msg += f" The top 3 account for {top3:.0f}%."
            out.append({"kind": "leader", "tone": "neutral", "widget_id": w["id"], "text": msg})
            return out
    ranked = base.sort_values(ascending=False)
    out.append({"kind": "leader", "tone": "neutral", "widget_id": w["id"],
                "text": f"{w['title']}: {ranked.index[0]} is highest ({_num(ranked.iloc[0])}); {ranked.index[-1]} is lowest ({_num(ranked.iloc[-1])})."})
    return out


def _quality_insights(df: pd.DataFrame, spec: dict[str, Any], ov: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = len(df)
    if n == 0:
        return out
    miss = df.isna().mean()
    bad = miss[miss > 0.05].sort_values(ascending=False)
    if len(bad):
        names = ", ".join(f"{c} ({v * 100:.0f}%)" for c, v in bad.head(3).items())
        out.append({"kind": "quality", "tone": "warning", "widget_id": None,
                    "text": f"Missing values: {names} — results using these columns may be understated."})
    if ov["duplicate_rows"]:
        out.append({"kind": "quality", "tone": "warning", "widget_id": None,
                    "text": f"{ov['duplicate_rows']:,} duplicate rows found ({ov['duplicate_rows'] / n * 100:.1f}% of the data)."})
    used = {f for w in spec.get("widgets", []) for f in widget_fields(w)}
    for c in [c for c in df.columns if c in used and pdt.is_numeric_dtype(df[c]) and not pdt.is_bool_dtype(df[c])][:6]:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(s) < 20:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        k = int(((s < q1 - 3 * iqr) | (s > q3 + 3 * iqr)).sum())
        if k and k / len(s) <= 0.05:
            out.append({"kind": "outlier", "tone": "warning", "widget_id": None,
                        "text": f"{k:,} unusually extreme value{'s' if k != 1 else ''} in {c} (beyond 3×IQR) — worth checking."})
            break
    return out


def build_ai_insights(df: pd.DataFrame, spec: dict[str, Any], ov: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ov = ov or overview(df)
    out: list[dict[str, Any]] = []
    widgets = sorted(
        (w for w in spec.get("widgets", []) if w.get("kind") == "chart"),
        key=lambda w: w.get("priority") or 999,
    )
    for w in widgets:
        try:
            out.extend(_chart_insights(df, w))
        except Exception:  # noqa: BLE001 — one odd widget must not drop the rest
            continue
    try:
        out.extend(_quality_insights(df, spec, ov))
    except Exception:  # noqa: BLE001
        pass
    return out[:MAX_AI_INSIGHTS]
