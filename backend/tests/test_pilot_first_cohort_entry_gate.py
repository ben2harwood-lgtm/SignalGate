"""Offline pilot-entry documentation contract, not a broker or acceptance test."""

from pathlib import Path


PILOT = Path(__file__).resolve().parents[2] / "docs" / "CONTROLLED_PROVIDER_PILOT.md"


def _doc() -> str:
    return PILOT.read_text(encoding="utf-8").lower()


def test_pilot_entry_refuses_failed_rc2_or_source_only_acceptance():
    text = _doc()
    for expected in (
        "first-cohort entry hold",
        "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2",
        "18 errors / 4 warnings",
        "0-error / 0-warning",
        "nonempty regenerated ex5",
        "draft/hold",
        "not_run",
    ):
        assert expected in text


def test_pilot_simulation_cannot_substitute_real_demo_broker_evidence():
    text = _doc()
    for expected in (
        "internal-only simulator",
        "not mt5 broker-demo acceptance",
        "actual mt5 demo-broker scenario receipts",
        "multi-fill",
        "weighted execution",
        "deal-versus-position",
        "tp1/tp2/tp3",
        "independent safety review",
    ):
        assert expected in text


def test_pilot_requires_external_entry_decision_and_never_auto_trades():
    text = _doc()
    for expected in (
        "not approval to activate",
        "independent security/pentest",
        "privacy",
        "contract",
        "regulatory",
        "no real-money trading or automatic copying",
    ):
        assert expected in text


def test_first_provider_runbook_never_uses_simulator_as_broker_pilot_entry():
    """Check the operator's last-mile instructions, not just the pilot plan."""
    root = Path(__file__).resolve().parents[2]
    runbook = (root / "docs" / "FIRST_PROVIDER_RUNBOOK.md").read_text(
        encoding="utf-8"
    ).lower()
    entry = runbook.split("## entry condition", 1)[1].split("## 1.", 1)[0]
    execution = runbook.split("## 6. connect demo execution", 1)[1].split(
        "## 7.", 1
    )[0]

    for required in (
        "hold — no external cohort",
        "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2",
        "18 errors / 4 warnings",
        "independently reviewed",
    ):
        assert required in entry

    for required in (
        "full 40-character candidate sha",
        "matching green ci",
        "0-error / 0-warning",
        "fresh nonempty **ex5**",
        "genuine broker-demo scenario receipts",
        "pr #60",
        "multi-fill",
        "deal-versus-position",
        "tp1/tp2/tp3",
        "uncertain-reconciliation",
        "internal-only, broker-free rehearsal",
        "**synthetic**",
        "**not_run**",
        "no real-money trading or automatic copying",
    ):
        assert required in execution
    assert "use the accepted demo mt5 setup or the simulator." not in execution
