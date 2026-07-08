"""Real-Gemini integration test for C39 prompt-cache token accounting (Phase 14).

Requires `AGENT_GEMINI_API_KEY` in `.env` — the cached-token field is
Gemini-specific (`usage_metadata.cached_content_token_count`), so this test
skips unless the resolved provider is Gemini (anthropic/openrouter honestly
report 0 this phase and would fail the > 0 assertion by design).

WITHIN-RUN design (redesigned after the first gate attempt)
-----------------------------------------------------------
The first fixture (one 4-row/3-col CSV, two consecutive asks) failed for two
structural reasons, confirmed by the auditor:

1. **Prompt too small for the implicit cache.** ~2.7K prompt tokens per call is
   an order of magnitude below the regime where Gemini's implicit cache
   reliably engages. The Step-0 spike (2026-07-08) measured ~74% cache hits
   with a byte-identical ~16.5K-token prefix; at ~2.7K it measured 0.
2. **Cross-run identity is broken by design.** After turn 1 the memory-facts
   extraction MUTATES the `[tag, datasets, MEMORY, history, question]` prefix
   between run 1 and run 2 — only WITHIN-run identity is guaranteed.

So this test asserts WITHIN-run caching on ONE ask: the plan prompt's prefix
through `## Question` is assembled once per run (`setup` builds
`dataset_context` into state; memory/history/question are state-held), so
iterations 2+ of the SAME run repeat a byte-identical prefix — exactly
production's ReAct pattern. `tokens_cached` accumulates per plan call, so a
multi-iteration run MUST report > 0 while a cold single-call run is
legitimately 0 (and is treated as a fixture failure, not a capture bug).

Prompt-size engineering (target: the proven >= ~16.5K-token regime, floor 8-10K)
--------------------------------------------------------------------------------
All context below is generated OFFLINE (no LLM involved in building it):

- 10 datasets x 6 columns each. Exactly 6 columns keeps every catalog line in
  the FULL column listing (C33 compression in `_catalog_block` collapses any
  dataset with > 6 columns to a 6-name preview, which would DEFLATE the prompt).
- Each dataset gets 20 C31 `context_facts` (the compress cap) of ~320 chars,
  written directly to `datasets.context_facts` — `setup` folds them verbatim
  into the catalog notes, exactly as production does for compressed notes.
- Measured arithmetic: 10 datasets x (20 facts x ~320 chars + ~330-char column
  header) ~= 66K chars of catalog, plus the ~9K-char `plan_action.md` system
  prompt and scaffolding ~= ~77K chars/call ~= **~16-18K prompt tokens per
  call** at ~4.2 chars/token — at/above the spike's proven ~16.5K regime,
  nowhere near the 2.7K floor that failed. An offline size assertion enforces
  this before any real call is spent.

Facts deliberately contain NO data values, and the question demands exact
computed numbers from two different datasets — so a FINAL ANSWER on the first
plan call is implausible and the run needs >= 2 iterations (call 2+ hit the
cache). If the run somehow finishes in one iteration the test fails with an
explicit "fixture failed to induce iterations" diagnostic.

SCOPED, budget-conscious: ONE session, ONE real ask (run ONCE at the gate).
"""
import io

import pytest

from db.models import DatasetRow, QueryRunRow
from db.session import create_db_session


@pytest.fixture
def _require_gemini_provider():
    """Skip unless the resolved provider is the real Gemini (cached tokens are
    Gemini-only this phase — see spec/capabilities/prompt-cache-accounting.md)."""
    from llm.client import _resolve_provider_name

    if _resolve_provider_name() != "gemini":
        pytest.skip(
            "C39 cached-token capture is Gemini-specific — set "
            "AGENT_GEMINI_API_KEY in .env (and no overriding provider)"
        )


# --------------------------------------------------------------------------- #
# Offline fixture generation (deterministic; no LLM anywhere in here)
# --------------------------------------------------------------------------- #

_N_DATASETS = 10
_FACTS_PER_DATASET = 20  # the C31 compress cap — production never stores more
_ROWS_PER_DATASET = 8

# Five long numeric-column stems + one label column per dataset = exactly 6
# columns, the C33 threshold below which `_catalog_block` always emits the FULL
# column listing (7+ columns would be compressed to a preview and shrink the
# prompt — the opposite of what this fixture needs).
_COLUMN_STEMS = (
    "recognized_subscription_revenue_gross_of_discounts_usd",
    "invoiced_billing_units_net_of_cancellations_count",
    "active_paying_subscriber_accounts_end_of_period_count",
    "customer_support_tickets_opened_within_sla_count",
    "order_fulfilment_latency_p95_business_hours_value",
)

# The generated catalog material (facts + column headers) must exceed this many
# chars (~11K+ tokens before the ~9K-char system prompt is even added) so a
# future fixture shrink fails OFFLINE instead of wasting a real-key gate run.
_MIN_CATALOG_CHARS = 45_000


def _numeric_columns(d: int) -> list[str]:
    return [f"{stem}_series_{d:02d}" for stem in _COLUMN_STEMS]


def _dataset_csv(d: int) -> tuple[str, str]:
    """(filename, csv_text) for synthetic dataset `d` — deterministic values."""
    label_col = f"fiscal_period_label_series_{d:02d}"
    numeric = _numeric_columns(d)
    lines = [",".join([label_col, *numeric])]
    for r in range(_ROWS_PER_DATASET):
        values = [(d + 1) * 1000 + r * 10 + c for c in range(len(numeric))]
        lines.append(",".join([f"2025-P{r + 1:02d}", *(str(v) for v in values)]))
    return f"metric_series_{d:02d}.csv", "\n".join(lines) + "\n"


def _dataset_facts(d: int) -> list[str]:
    """20 realistic C31-style provenance facts (~320 chars each).

    Deliberately value-free: they describe HOW each column is produced, never
    WHAT it sums/averages to, so the model cannot answer the question from the
    catalog alone and must execute pandas (forcing >= 2 ReAct iterations).
    """
    numeric = _numeric_columns(d)
    facts = []
    for i in range(_FACTS_PER_DATASET):
        col = numeric[i % len(numeric)]
        facts.append(
            f"fact {i + 1:02d}: `{col}` is ingested nightly by warehouse job "
            f"ws-{d:02d}-{i:02d}, reconciled against the corporate ledger "
            f"extract before publication, quality-scored by the data-platform "
            f"team each cycle, and revised only during the annual restatement "
            f"window for reporting slot {d:02d}."
        )
    return facts


# The question demands EXACT computed numbers from two different datasets, so a
# one-shot FINAL ANSWER (no pandas action) would be a hallucination — realistic
# behaviour is 2-4 plan calls, and every call after the first repeats the
# byte-identical [system, tag, datasets, memory, question] prefix.
_QUESTION = (
    "Using only the uploaded data, do all of the following and show the exact "
    "numbers: (1) compute the exact SUM of the column "
    f"`{_numeric_columns(2)[0]}` in metric_series_02.csv; "
    "(2) compute the exact MEAN of the column "
    f"`{_numeric_columns(7)[3]}` in metric_series_07.csv; "
    "(3) state which of those two computed numbers is larger."
)


def _upload_all(client) -> dict[str, list[str]]:
    """Upload every synthetic dataset; return {dataset_id: facts} to seed."""
    facts_by_id: dict[str, list[str]] = {}
    for d in range(_N_DATASETS):
        filename, csv_text = _dataset_csv(d)
        files = {"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")}
        r = client.post("/upload", files=files)
        assert r.status_code == 200, r.text
        facts_by_id[r.json()["data"]["dataset_id"]] = _dataset_facts(d)
    return facts_by_id


# --------------------------------------------------------------------------- #
# Test
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("_require_llm_key", "_require_gemini_provider")
def test_multi_iteration_run_records_cached_tokens(api_client):
    # ---- OFFLINE size gate: fail before spending a real call if the fixture
    # ever shrinks out of the proven implicit-cache regime. -------------------
    catalog_chars = sum(
        sum(len(f) for f in _dataset_facts(d)) + len(",".join(_numeric_columns(d)))
        for d in range(_N_DATASETS)
    )
    assert catalog_chars >= _MIN_CATALOG_CHARS, (
        f"fixture too small for the implicit-cache regime: generated only "
        f"{catalog_chars} catalog chars (< {_MIN_CATALOG_CHARS}). The Step-0 "
        "spike showed ~2.7K prompt tokens does NOT reliably hit Gemini's "
        "implicit cache — enlarge the fixture, do not weaken this floor."
    )

    facts_by_id = _upload_all(api_client)

    # Seed C31 compressed facts directly (exactly the artifact production
    # stores; `setup` folds them verbatim into each catalog line's notes).
    with create_db_session() as s:
        for dataset_id, facts in facts_by_id.items():
            row = s.get(DatasetRow, dataset_id)
            assert row is not None
            row.context_facts = facts

    try:
        # ---- ONE real ask (budget rule): a multi-step exact-number question
        # across two datasets -> >= 2 plan calls sharing a byte-identical
        # ~14-16K-token prefix -> iterations 2+ produce the cache hits. -------
        resp = api_client.post(
            "/ask",
            json={"question": _QUESTION, "skip_clarification": True},
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        assert d["type"] == "answer"
        assert d["status"] == "completed", d
        assert "[stub]" not in d["answer_markdown"], "real provider not used"
        session_id = d["session_id"]
        assert session_id

        # ---- Guard: the cached>0 invariant only holds from iteration 2 on.
        # A single-iteration run means the FIXTURE failed to induce iterations
        # (the question was answerable without pandas) — say so explicitly
        # instead of mis-blaming the capture plumbing.
        assert d["iteration_count"] >= 2, (
            "fixture failed to induce a second ReAct iteration "
            f"(iteration_count={d['iteration_count']}): the within-run cache "
            "assertion needs >= 2 plan calls, and a cold single-call run is "
            "legitimately tokens_cached=0. Make the question require more "
            "pandas steps — this is NOT a token-capture failure."
        )

        # ---- The C39 invariants -------------------------------------------
        assert isinstance(d["tokens_cached"], int)
        assert d["tokens_cached"] > 0, (
            "multi-iteration run reported no cached tokens despite a "
            "byte-identical multi-thousand-token prompt prefix repeating "
            f"across {d['iteration_count']} iterations (tokens_cached="
            f"{d['tokens_cached']}, tokens_input={d['tokens_input']})"
        )
        # Cached is a SUBSET of the run's cumulative input.
        assert d["tokens_cached"] <= d["tokens_input"]

        # Persisted on the row (survives reload/resume)...
        run_id = d["run_id"]
        with create_db_session() as s:
            row = s.get(QueryRunRow, run_id)
            assert row is not None
            assert (row.tokens_cached or 0) == d["tokens_cached"]

        # ...and reported by GET /runs/{run_id}, the session turn, /stats/daily.
        run = api_client.get(f"/runs/{run_id}").json()["data"]
        assert run["tokens_cached"] == d["tokens_cached"]

        detail = api_client.get(f"/sessions/{session_id}").json()["data"]
        turn = next(t for t in detail["turns"] if t["run_id"] == run_id)
        assert turn["tokens_cached"] == d["tokens_cached"]

        stats = api_client.get("/stats/daily").json()["data"]
        assert stats["tokens_cached"] >= d["tokens_cached"]
        assert stats["last_tokens_cached"] == d["tokens_cached"]

        # Cleanup below deletes the run row via cascade — leave a record of the
        # observed values in the gate output (visible with `-s` / on failure).
        print(
            f"[gate-record] tokens_cached={d['tokens_cached']} "
            f"tokens_input={d['tokens_input']} "
            f"iteration_count={d['iteration_count']}"
        )
    finally:
        # Remove the synthetic datasets (and their stored parquet files).
        for dataset_id in facts_by_id:
            api_client.delete(f"/datasets/{dataset_id}")
