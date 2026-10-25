"""Prevent a superseded July checklist from masquerading as release assurance.

These are source-document contract tests, not MT5, security or external receipts.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "SAFETY_RULES.md"


def _rules() -> str:
    return DOC.read_text(encoding="utf-8")


def test_safety_rules_follow_current_canonical_authority():
    text = _rules()
    for pointer in ("AGENTS.md", "SIGNALGATE-STATUS.md", "RELEASE_GATES.md"):
        assert pointer in text
    assert "historical and superseded" in text.lower()
    for path in (
        ROOT / "AGENTS.md",
        ROOT / "SIGNALGATE-STATUS.md",
        ROOT / "docs" / "RELEASE_GATES.md",
    ):
        assert path.is_file()


def test_old_prototype_exclusions_are_not_current_safety_assertions():
    text = _rules().lower()
    for obsolete in (
        "no ai parsing",
        "no public landing page",
        "no customer dashboard beyond admin logs",
        "no extra product features",
        "these constraints are non-negotiable for v1 and are enforced in code",
    ):
        assert obsolete not in text
    assert "screenshot extraction can exist upstream" in text


def test_failed_frozen_rc2_is_not_rebranded_as_broker_acceptance():
    text = _rules()
    for required in (
        "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2",
        "35464044898",
        "18 errors and 4 warnings",
        "Do not use frozen RC2 for broker-demo acceptance.",
        "fresh EX5",
        "genuine controlled",
        "PR #60",
        "deal-versus-position identity",
    ):
        assert required in text
    assert "G3 external execution acceptance" in text
    assert "G9 pilot" in text
    assert "NOT PASSED" in text


def test_demo_only_human_authority_and_fail_closed_uncertainty_are_explicit():
    text = _rules().lower()
    for required in (
        "demo only",
        "explicit, per-transaction yes",
        "no unattended auto-copy",
        "never",
        "blind resubmission",
        "real-money trading",
        "synthetic fixtures cannot satisfy",
    ):
        assert required in text
