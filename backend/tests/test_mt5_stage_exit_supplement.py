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


def test_all_thirteen_broker_demo_scenarios_are_explicitly_unexecuted():
    rows = _scenario_rows(RECEIPT.read_text(encoding="utf-8"))
    assert set(rows) == {f"S{n}" for n in range(1, 14)}
    assert all(row[3] == "NOT_RUN" and not row[4] for row in rows.values())


def test_negative_cases_prohibit_false_tp_and_sl_events():
    rows = _scenario_rows(RECEIPT.read_text(encoding="utf-8"))
    assert "TP1_CLOSE_SUCCESS" in rows["S2"][2]
    assert "TP3_CLOSE_SUCCESS" in rows["S4"][2]
    assert "DEAL_REASON_SL" in rows["S5"][2]
    assert "Different command" in rows["S6"][2]
    assert "ResultRetcode()" in rows["S7"][2]
    assert "SL_MOVE_BREAKEVEN_SUCCESS" in rows["S7"][2]
    assert "SL_MOVE_TP1_SUCCESS" in rows["S7"][2]
    assert "SL_MOVE_LOCK_PROFIT_SUCCESS" not in rows["S7"][2]
    assert "EA restart" in rows["S8"][1]
    assert "FAIL/INCONCLUSIVE" in rows["S8"][2]
    assert "orphan detection" in rows["S8"][2]
    assert "TP3_CLOSE_SUCCESS" in rows["S9"][2]
    assert "DEAL_TIME_MSC" in rows["S10"][2]
    assert "STOP_LOSS_HIT" in rows["S10"][2]
    assert "deal-ticket order" in rows["S10"][2]


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
    assert "thirteen NOT_RUN scenarios" in text


def test_split_fill_rollback_receipt_never_infers_flatness_from_close_request():
    text = RECEIPT.read_text(encoding="utf-8")
    rows = _scenario_rows(text)
    assert "Partially filled split command" in rows["S11"][1]
    for required in (
        "No final `FAILED` or flat receipt",
        "`PositionClose`",
        "`ResultRetcode()`",
        "post-close broker position/deal history",
        "durable reconciliation-required HOLD",
        "no further order polling or broker retry",
        "never close an unrelated position",
    ):
        assert required in rows["S11"][2]

    subcases = {}
    for line in text.splitlines():
        if line.startswith("| R"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            assert len(cells) == 5, line
            assert cells[0] not in subcases
            subcases[cells[0]] = cells
    assert set(subcases) == {f"R{n}" for n in range(1, 6)}
    assert all(row[3] == "NOT_RUN" and not row[4] for row in subcases.values())
    for case, proof in {
        "R1": "server `ResultRetcode()` rejects close",
        "R2": "stop/freeze/rejection",
        "R3": "EA restarts",
        "R4": "authoritative broker deal history confirms the account flat",
        "R5": "times out or returns 409",
    }.items():
        assert proof in subcases[case][1]
    assert "S11 may be marked PASS **only if R1–R5 each have real broker-DEMO evidence" in text
    assert "matching backend audit receipt" in text
    assert "Backend status and reconciliation semantics must be corrected" in text

def test_later_child_lot_preflight_needs_zero_broker_order_demo_receipt():
    """S12 is demo acceptance, not a claim that source-only checks prove a fill."""
    text = RECEIPT.read_text(encoding="utf-8")
    row = _scenario_rows(text)["S12"]
    assert "TP2/TP3 split-child lot is invalid" in row[1]
    for required in (
        "before the FIRST broker order",
        "LOT_SIZE_INVALID",
        "ZERO broker order/deal tickets",
        "no rollback attempt",
        "broker min/max/step",
        "never infer broker proof from CI",
    ):
        assert required in row[2]
    assert row[3] == "NOT_RUN" and not row[4]
    assert "Actual later-child broker rejection after a prior fill" in text


def test_single_ticket_unknown_broker_outcome_needs_real_reconciliation():
    """Source-anchored S13/U1–U5 are unrun DEMO acceptance obligations."""
    text = RECEIPT.read_text(encoding="utf-8")
    row = _scenario_rows(text)["S13"]
    assert "Single-ticket broker send" in row[1]
    for proof in ("TRADE_RETCODE_PLACED", "ResultVolume()", "no new order",
                  "across restart", "account-flat proof", "No terminal `FAILED`"):
        assert proof in row[2]
    assert row[3] == "NOT_RUN" and row[4] == ""

    subcases = {}
    for line in text.splitlines():
        if line.startswith("| U"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            assert len(cells) == 5, line
            assert cells[0] not in subcases, "Duplicate U case"
            subcases[cells[0]] = cells
    assert set(subcases) == {f"U{n}" for n in range(1, 6)}
    assert all(row[3] == "NOT_RUN" and not row[4] for row in subcases.values())
    for case, proof in {
        "U1": "market send times out",
        "U2": "TRADE_RETCODE_PLACED",
        "U3": "ResultVolume()",
        "U4": "restarts before broker truth",
        "U5": "rejects reconciliation (409)",
    }.items():
        assert proof in subcases[case][1]
    for required in ("87a0ef3a1edf2e50c19b86370cd8355507df045d",
                     "S13 may be marked PASS **only after all U1–U5",
                     "actual", "independent review", "FAIL/INCONCLUSIVE"):
        if required != "actual":
            assert required in text
