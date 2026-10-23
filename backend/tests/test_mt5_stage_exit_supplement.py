"""Receipt contract for the unaccepted PR #60 stage-exit broker-demo gate.

These are DOCUMENT checks. They do not connect to MT5 or constitute broker proof.
"""
from pathlib import Path

RECEIPT = Path(__file__).resolve().parents[2] / "docs/evidence/MT5_STAGE_EXIT_SUPPLEMENT_TEMPLATE.md"


def _scenario_rows(text: str):
    rows = {}
    for line in text.splitlines():
        if line.startswith("| S"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            assert len(cells) == 5, line
            assert cells[0] not in rows, "Repeated scenario ID must not hide a result"
            rows[cells[0]] = cells
    return rows


def test_all_nine_broker_demo_scenarios_are_explicitly_unexecuted():
    rows = _scenario_rows(RECEIPT.read_text(encoding="utf-8"))
    assert set(rows) == {f"S{n}" for n in range(1, 10)}
    assert all(row[3] == "NOT_RUN" and not row[4] for row in rows.values())


def test_negative_cases_prohibit_false_tp_and_sl_events():
    rows = _scenario_rows(RECEIPT.read_text(encoding="utf-8"))
    assert "TP1_CLOSE_SUCCESS" in rows["S2"][2]
    assert "TP3_CLOSE_SUCCESS" in rows["S4"][2]
    assert "DEAL_REASON_SL" in rows["S5"][2]
    assert "Different command" in rows["S6"][2]
    assert "ResultRetcode()" in rows["S7"][2]
    assert "reconciliation ambiguity" in rows["S8"][2]
    assert "TP3_CLOSE_SUCCESS" in rows["S9"][2]


def test_positive_tp_attribution_requires_own_child_broker_reason():
    rows = _scenario_rows(RECEIPT.read_text(encoding="utf-8"))
    assert "OWN `DEAL_REASON_TP`" in rows["S1"][1]
    assert "its own `DEAL_REASON_TP`" in rows["S3"][2]
    assert "its OWN `DEAL_REASON_TP`" in rows["S9"][2]
    for stage in ("S1", "S3"):
        assert "at most once" in rows[stage][2]


def test_template_does_not_allow_ci_to_pass_external_acceptance():
    text = RECEIPT.read_text(encoding="utf-8")
    for required in (
        "This is a **supplement**", "full 40-character commit SHA", ".mq5` SHA-256",
        "MetaEditor compiler version", "ACCOUNT_TRADE_MODE_DEMO",
        "DEAL_POSITION_ID", "DEAL_ENTRY", "DEAL_REASON", "ResultRetcode()",
        "per-transaction human", "Broker-free simulations", "independent reviewer",
        "whole supplement NOT ACCEPTED", "External application/security", "WhatsApp activation",
    ):
        assert required in text


def test_evidence_index_links_supplement_without_approval_claim():
    evidence_readme = RECEIPT.parent / "README.md"
    text = evidence_readme.read_text(encoding="utf-8")
    assert "MT5_STAGE_EXIT_SUPPLEMENT_TEMPLATE.md" in text
    assert "nine NOT_RUN scenarios" in text
