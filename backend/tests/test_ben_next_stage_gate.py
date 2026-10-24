"""Protect the operator checklist against re-admitting the failed frozen RC2 EA.

These are documentation contract checks, not MetaEditor or broker acceptance.
"""

from pathlib import Path


CHECKLIST = (
    Path(__file__).resolve().parents[2] / "docs" / "BEN_NEXT_STAGE_CHECKLIST.md"
)


def test_frozen_rc2_compiler_failure_is_explicit():
    text = CHECKLIST.read_text(encoding="utf-8")
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in text
    assert "18 errors / 4 warnings" in text
    assert "35464044898" in text
    assert "Do not use frozen RC2 for broker-demo scenarios." in text
    assert "Compile the exact RC EA in the target MetaEditor" not in text


def test_successor_requires_new_exact_source_proof_and_review():
    text = CHECKLIST.read_text(encoding="utf-8")
    assert "PR #60 remains DRAFT/HOLD" in text
    assert "independent exact-head code/security review" in text
    assert "newly generated, nonempty EX5" in text
    assert "0 errors and 0 warnings" in text
    assert "new pinned candidate" in text


def test_broker_scenarios_remain_distinct_from_synthetic_receipts():
    text = CHECKLIST.read_text(encoding="utf-8")
    assert "NOT_RUN" in text
    assert "PR #89" in text
    assert "Synthetic tests and source assertions are not MT5 acceptance." in text
    assert "No real-money trading, automatic copying" in text
