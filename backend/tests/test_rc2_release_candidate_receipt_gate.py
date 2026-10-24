"""Contract: historical frozen RC2 CI success must not imply MT5 acceptance.

These offline documentation assertions do not compile an EA, connect to MT5,
execute broker orders, or replace independent/external receipts.
"""
from pathlib import Path

RECORD = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "RELEASE_CANDIDATE_2026-09-19.md"
)


def test_rc2_receipt_preserves_original_machine_success_and_failed_compiler() -> None:
    record = RECORD.read_text(encoding="utf-8")
    assert "852a6bc9ca9f0651b34e87b63e86c65669130767" in record
    assert "35459129106" in record  # Original machine CI SUCCESS.
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in record
    assert "35464044898" in record  # Official exact frozen-source compile.
    assert "18 errors" in record
    assert "4 warnings" in record
    assert "not a MetaEditor pass" in record


def test_rc2_receipt_blocks_failed_frozen_ea_broker_demo_acceptance() -> None:
    record = RECORD.read_text(encoding="utf-8")
    assert "Frozen RC2 must not be used for MT5 broker-demo" in record
    assert "not an eligible MT5 broker-demo" in record
    assert "NOT_RUN" in record
    assert "PR #60" in record
    assert "newly generated EX5" in record
    assert "independently reviewed successor" in record


def test_rc2_receipt_does_not_restore_disproved_future_acceptance_claims() -> None:
    record = RECORD.read_text(encoding="utf-8")
    assert "RC2 supersedes RC1 for new acceptance work" not in record
    assert "Still required against RC2:" not in record
    assert "this candidate is suitable to proceed to the external/manual acceptance sequence" not in record
    assert "no real-money or automatic-copy execution is authorised" in record
