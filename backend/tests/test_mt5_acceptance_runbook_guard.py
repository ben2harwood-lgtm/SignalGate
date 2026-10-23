"""Document-contract guards: frozen RC2 must not be presented as demo-ready."""
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "MT5_ACCEPTANCE.md"


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_frozen_rc2_failure_explicitly_disqualifies_broker_demo() -> None:
    text = _runbook()
    assert "Frozen RC2 is NOT a valid broker-demo onboarding candidate" in text
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in text
    assert "18 errors / 4 warnings" in text
    assert "35464044898" in text
    assert "separately reviewed" in text


def test_rc2_command_is_historical_reproduction_only() -> None:
    text = _runbook()
    assert "Historical RC2 *failure reproduction only*" in text
    assert "do **not** use this command as a passing acceptance candidate" in text
    assert "- named candidate ref + exact commit SHA;" in text
    assert "It resolves the named candidate ref" in text


def test_stage_close_attribution_requires_specific_broker_exit() -> None:
    text = _runbook()
    assert "specific child position/deal's" in text
    assert "reduced open-position count" in text
    assert "manual final close after an earlier TP" in text
    assert "broker-mutated identifiers/comments" in text
    assert "PR #60's" in text
    assert "machine-tested but not externally accepted" in text
