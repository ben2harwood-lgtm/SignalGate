"""Static incident-runbook regression: operational text is not broker evidence."""

from pathlib import Path
import re

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "INCIDENT_RUNBOOKS.md"


def _hold_section() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^## MT5 DEMO partial-fill or broker identity uncertainty — HOLD\s*\n"
        r"(.*?)(?=^## |\Z)",
        text,
    )
    assert match, "MT5 ambiguous-fill incident HOLD section disappeared"
    return re.sub(r"\s+", " ", match.group(1)).lower()


def test_incident_runbook_requires_typed_broker_identity():
    section = _hold_section()
    for token in ("deal_order", "deal_position_id", "position_identifier",
                  "position_ticket", "all opening deals", "do not equate",
                  "demo account"):
        assert token in section, f"broker identity requirement missing: {token}"


def test_incident_runbook_refuses_false_execution_and_stage_receipts():
    section = _hold_section()
    for token in ("pause", "never blindly resend", "unknown / reconciliation required",
                  "fully_closed", "matched", "tp1/tp2/tp3",
                  "split rollback", "broker-reported exit reasons"):
        assert token in section, f"fail-closed response missing: {token}"


def test_incident_runbook_does_not_turn_synthetic_checks_into_acceptance():
    section = _hold_section()
    for token in ("frozen rc2", "18 errors / 4 warnings",
                  "35464044898", "not_run", "independent review",
                  "private", "external pilot"):
        assert token in section, f"acceptance/provenance limit missing: {token}"
