"""Offline document-contract checks; these are NOT broker acceptance tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / "docs" / "BETA_ACCEPTANCE.md"


def _section(start: str, end: str) -> str:
    document = CHECKLIST.read_text(encoding="utf-8")
    assert document.count(start) == 1
    assert document.count(end) == 1
    return document.split(start, 1)[1].split(end, 1)[0]


def test_failed_frozen_rc2_never_passes_beta_from_newer_compile():
    text = CHECKLIST.read_text(encoding="utf-8")
    for required in (
        "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2",
        "18 errors / 4 warnings",
        "FAILED",
        "cannot be used as the approved broker-demo candidate",
        "does not retroactively pass this frozen RC2",
        "DRAFT/HOLD",
    ):
        assert required in text


def test_beta_g3_requires_source_bound_compiled_binary_and_real_broker_proof():
    mt5 = _section("## MT5 / execution gate", "## Provider onboarding gate")
    for required in (
        "exact Git candidate SHA",
        "EA source SHA-256",
        "independent code/safety review",
        "0 errors / 0 warnings",
        "nonempty regenerated EX5",
        "demo-broker",
        "multi-fill",
        "weighted execution price",
        "deal/order/position identities",
        "no blind resend",
        "TP1/TP2/TP3",
        "docs/MT5_ACCEPTANCE.md",
        "NOT_RUN",
    ):
        assert required.lower() in mt5.lower()


def test_beta_cannot_substitute_synthetic_evidence_or_silent_membership():
    document = CHECKLIST.read_text(encoding="utf-8")
    for required in (
        "Beta is demo-account only",
        "automatic copying",
        "Synthetic API snapshots",
        "machine evidence only",
        "actual retained terminal/broker receipt",
        "one-time feed invite",
        "cannot silently attach a subscriber",
    ):
        assert required.lower() in document.lower()
