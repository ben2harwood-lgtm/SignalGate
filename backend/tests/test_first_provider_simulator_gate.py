"""Runbook contracts: synthetic demo evidence must not become external pilot approval.

Offline text assertions only. These do not exercise MT5, providers, networks, or
any acceptance gate.
"""
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "FIRST_PROVIDER_RUNBOOK.md"


def _demo_execution_section() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    start = "## 6. Connect demo execution\n"
    stop = "\n## 7. Mandatory pre-cohort scenarios"
    assert text.count(start) == 1
    section = text.split(start, 1)[1]
    assert stop in section
    return section.split(stop, 1)[0]


def test_first_provider_simulator_is_broker_free_not_external_acceptance():
    section = _demo_execution_section()
    assert "broker-free simulator" in section
    assert "synthetic/API evidence" in section
    assert "`NOT_RUN`" in section
    assert "not a substitute" in section
    assert "Use the accepted demo MT5 setup or the simulator." not in section


def test_first_provider_requires_candidate_broker_and_independent_proof():
    section = _demo_execution_section()
    for phrase in (
        "frozen RC2 failed",
        "independently reviewed successor candidate",
        "MetaEditor",
        "0-error / 0-warning",
        "regenerated **EX5**",
        "exact candidate",
        "real MT5 DEMO broker",
        "order/deal/position identity",
        "PR #60",
        "docs/BETA_ACCEPTANCE.md",
    ):
        assert phrase in section


def test_first_provider_paused_until_actual_acceptance():
    section = _demo_execution_section()
    assert "Keep the provider/feed paused and do not start the external pilot" in section
    assert "while any required receipt or independent acceptance is missing" in section
    assert "Real-money trading and automatic copying remain prohibited." in section
