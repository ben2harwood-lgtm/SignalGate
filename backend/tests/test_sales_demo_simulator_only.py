"""Static guard: the internal sales script must not imply MT5/pilot approval."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs" / "SALES_DEMO.md"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_sales_rehearsal_is_broker_free_and_internal():
    text = _script()
    assert "INTERNAL Simulator-Only Sales Rehearsal" in text
    for term in (
        "broker-free simulator",
        "SIMULATED / NOT BROKER VERIFIED",
        "NOT MT5",
        "No public backend",
        "real Telegram",
        "No real-money trading",
    ):
        assert term.lower() in text.lower()
    assert "Use the simulator/demo MT5 account" not in text


def test_sales_demo_never_conflates_synthetic_and_real_execution():
    text = _script().lower()
    for term in (
        "not proof of a single real broker fill",
        "multi-deal fill accounting",
        "deal/position identity",
        "reconciliation, restart recovery or split rollback",
        "g3 execution acceptance",
        "g8 external assurance",
        "g9 pilot entry",
        "not passed",
    ):
        assert term in text


def test_sales_rehearsal_withholds_external_acceptance():
    text = _script()
    for marker in (
        "35464044898",
        "18 errors / 4 warnings",
        "PR #60",
        "new EX5",
        "independent review",
        "This script does not grant that",
        "EXTERNAL_ACCEPTANCE_HANDOFF.md",
    ):
        assert marker in text
    for p in (
        ROOT / "SIGNALGATE-STATUS.md",
        ROOT / "docs" / "MT5_ACCEPTANCE.md",
        ROOT / "docs" / "EXTERNAL_ACCEPTANCE_HANDOFF.md",
    ):
        assert p.is_file()
