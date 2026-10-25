"""Fail-closed checks for a broker snapshot contradicting an open execution.

Synthetic API fixtures only. No MetaTrader, broker connection or order placement.
"""
from __future__ import annotations

import pytest

from app import models
from app.database import SessionLocal
from .conftest import EA_HEADERS, create_signal, register_user

_SIGNAL = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _reported_execution(client, telegram_id: str) -> str:
    user = register_user(client, telegram_id)
    signal = create_signal(client, _SIGNAL)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": telegram_id},
    )
    assert approval.status_code == 200, approval.text
    command = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    assert command is not None
    command_id = command["command_id"]
    report = client.post(
        f"/commands/{command_id}/execution",
        json={
            "status": "SUCCESS",
            "broker_ticket": "9001",
            "executed_symbol": "XAUUSD",
            "executed_direction": "BUY",
            "executed_price": 2345.0,
            "lot_size": 0.01,
        },
        headers=EA_HEADERS,
    )
    assert report.status_code == 200, report.text
    return command_id


def _snapshot(lot_size: float = 0.01, executed_price: float = 2345.0) -> dict:
    return {
        "broker_tickets": ["9001"],
        "executed_symbol": "XAUUSD",
        "executed_direction": "BUY",
        "executed_price": executed_price,
        "lot_size": lot_size,
    }


@pytest.mark.parametrize(
    ("lot_size", "executed_price", "expected"),
    [
        (0.02, 2345.0, "existing_open_lot_size"),
        (0.005, 2345.0, "existing_open_lot_size"),
        (0.01, 2346.0, "existing_open_price"),
        (0.02, 2346.0, "existing_open_lot_size"),
    ],
)
def test_open_snapshot_discrepancy_is_conflict_and_does_not_rewrite_execution(
    client, lot_size, executed_price, expected
):
    cid = _reported_execution(client, "841")
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(lot_size, executed_price),
        headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert expected in response.json()["detail"]
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.lot_size == pytest.approx(0.01)
        assert execution.executed_price == pytest.approx(2345.0)
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert expected in audit.payload_json


def test_matching_open_snapshot_remains_idempotent(client):
    cid = _reported_execution(client, "842")
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(), headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"


def test_reported_partial_close_allows_lower_remaining_open_volume(client):
    cid = _reported_execution(client, "843")
    event = client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "TP1_CLOSE_SUCCESS", "stage": "TP1_DONE", "result": "SUCCESS"},
        headers=EA_HEADERS,
    )
    assert event.status_code == 200, event.text
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(lot_size=0.005), headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"

@pytest.mark.parametrize(
    "events",
    [
        [("TP1_CLOSE_SUCCESS", "TP1_DONE")],
        [("TP1_CLOSE_SUCCESS", "TP1_DONE"), ("TP2_CLOSE_SUCCESS", "TP2_DONE")],
    ],
    ids=["after-tp1", "after-tp2"],
)
@pytest.mark.parametrize("observed_lot_size", [0.02, 0.20])
def test_partial_close_snapshot_increase_conflicts_and_keeps_original_execution(
    client, events, observed_lot_size
):
    """A partial-close event is not authority to accept increased broker exposure."""
    cid = _reported_execution(client, "844")
    for event_type, stage in events:
        event = client.post(
            f"/commands/{cid}/management_event",
            json={"event_type": event_type, "stage": stage, "result": "SUCCESS"},
            headers=EA_HEADERS,
        )
        assert event.status_code == 200, event.text

    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(lot_size=observed_lot_size),
        headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "existing_open_lot_size" in response.json()["detail"]
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        assert original.lot_size == pytest.approx(0.01)
        assert original.executed_price == pytest.approx(2345.0)
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
            .payload_json
            .find("existing_open_lot_size")
            >= 0
        )


def test_second_partial_close_snapshot_allows_reduced_remaining_volume(client):
    cid = _reported_execution(client, "845")
    for event_type, stage in (
        ("TP1_CLOSE_SUCCESS", "TP1_DONE"),
        ("TP2_CLOSE_SUCCESS", "TP2_DONE"),
    ):
        event = client.post(
            f"/commands/{cid}/management_event",
            json={"event_type": event_type, "stage": stage, "result": "SUCCESS"},
            headers=EA_HEADERS,
        )
        assert event.status_code == 200, event.text
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(lot_size=0.002),
        headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"


@pytest.mark.parametrize("stored_children", [None, "[]"])
def test_missing_stored_broker_identity_refuses_snapshot_match(client, stored_children):
    """A matching price and size cannot substitute for original broker identity."""
    cid = _reported_execution(client, "846")
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        execution.broker_ticket = None
        execution.child_tickets_json = stored_children
        db.commit()

    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(), headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "missing_stored_broker_identity" in response.json()["detail"]
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.broker_ticket is None
        assert execution.child_tickets_json == stored_children
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "missing_stored_broker_identity" in audit.payload_json


@pytest.mark.parametrize("after_partial", [False, True], ids=["open", "after-tp1"])
def test_matching_ticket_does_not_authorize_untracked_extra_position(
    client, after_partial
):
    """A single familiar ticket must not mask an extra broker position ticket."""
    cid = _reported_execution(client, "847")
    if after_partial:
        event = client.post(
            f"/commands/{cid}/management_event",
            json={"event_type": "TP1_CLOSE_SUCCESS", "stage": "TP1_DONE", "result": "SUCCESS"},
            headers=EA_HEADERS,
        )
        assert event.status_code == 200, event.text

    snapshot = _snapshot(lot_size=0.005 if after_partial else 0.01)
    snapshot["broker_tickets"] = ["9001", "9002"]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "broker_tickets" in response.json()["detail"]
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        assert original.broker_ticket == "9001"
        assert original.lot_size == pytest.approx(0.01)
        assert original.executed_price == pytest.approx(2345.0)
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "broker_tickets" in audit.payload_json


def test_snapshot_can_match_subset_of_already_recorded_child_tickets(client):
    """A shrinking known-ticket set remains compatible with idempotent matching."""
    cid = _reported_execution(client, "848")
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        original.child_tickets_json = '["9001", "9002"]'
        db.commit()
    snapshot = _snapshot()
    snapshot["broker_tickets"] = ["9002"]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"


@pytest.mark.parametrize(
    ("event_type", "event_result", "final_status"),
    [
        ("FULLY_CLOSED", "SUCCESS", "FULLY_CLOSED"),
        ("STOP_LOSS_HIT", "SUCCESS", "FULLY_CLOSED"),
        ("FAILED_MANAGEMENT", "FAILED", "FAILED"),
    ],
)
def test_terminal_command_refuses_later_matching_open_position_snapshot(
    client, event_type, event_result, final_status
):
    """A stored SUCCESS ticket cannot resurrect a closed/failed command."""
    cid = _reported_execution(client, "849")
    event = client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": event_type, "result": event_result},
        headers=EA_HEADERS,
    )
    assert event.status_code == 200, event.text
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(), headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "command_state" in response.json()["detail"]
    with SessionLocal() as db:
        command = db.query(models.Command).filter_by(id=cid).one()
        assert command.status == final_status
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.status == "SUCCESS"
        assert execution.broker_ticket == "9001"
        assert execution.lot_size == pytest.approx(0.01)
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "command_state" in audit.payload_json


@pytest.mark.parametrize("other_broker_symbol", ["XAUUSD.b", "XAUUSDmicro"])
def test_same_requested_prefix_does_not_validate_different_executed_symbol(
    client, other_broker_symbol
):
    """Requested-symbol prefix is not sufficient broker instrument identity."""
    cid = _reported_execution(client, "850")
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        original.executed_symbol = "XAUUSD.a"
        db.commit()
    snapshot = _snapshot()
    snapshot["executed_symbol"] = other_broker_symbol
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "existing_executed_symbol" in response.json()["detail"]
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.executed_symbol == "XAUUSD.a"
        assert execution.broker_ticket == "9001"
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "existing_executed_symbol" in audit.payload_json


def test_same_recorded_broker_suffix_allows_matching_snapshot(client):
    cid = _reported_execution(client, "851")
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        original.executed_symbol = "XAUUSD.a"
        db.commit()
    snapshot = _snapshot()
    snapshot["executed_symbol"] = "XAUUSD.a"
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"



@pytest.mark.parametrize(
    ("stored_children", "observed_ticket"),
    [
        ('{"9002":"forged-key"}', "9002"),
        ('"9002"', "9001"),
        ('["9002", null]', "9002"),
        ('["9002", true]', "9002"),
        ('["9002", {"nested":"ticket"}]', "9002"),
        ('["9002", ""]', "9001"),
    ],
    ids=["object-keys", "scalar-string", "null", "boolean", "nested", "empty-id"],
)
def test_invalid_stored_child_tickets_never_authorize_broker_match(
    client, stored_children, observed_ticket
):
    """Malformed persisted child evidence cannot authorize any open snapshot."""
    cid = _reported_execution(client, "852")
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        original.child_tickets_json = stored_children
        db.commit()

    snapshot = _snapshot()
    snapshot["broker_tickets"] = [observed_ticket]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "stored_ticket_payload" in response.json()["detail"]
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        assert original.broker_ticket == "9001"
        assert original.child_tickets_json == stored_children
        assert original.lot_size == pytest.approx(0.01)
        assert original.executed_price == pytest.approx(2345.0)
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "stored_ticket_payload" in audit.payload_json


@pytest.mark.parametrize("stored_children", ['["9001", "9002"]', "[9001, 9002]"])
def test_valid_child_ticket_list_can_match_known_surviving_position(
    client, stored_children
):
    """Retain compatibility with real string and legacy integral ticket IDs."""
    cid = _reported_execution(client, "853")
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        original.child_tickets_json = stored_children
        db.commit()
    snapshot = _snapshot()
    snapshot["broker_tickets"] = ["9002"]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"


@pytest.mark.parametrize(
    "unusable_tickets",
    [[""], [" \t "], ["", "   "]],
    ids=["empty", "whitespace", "mixed-empty"],
)
def test_unusable_ticket_snapshot_has_durable_private_conflict_receipt(
    client, unusable_tickets
):
    """A ticketless snapshot fails closed *and* retains an audit receipt."""
    cid = _reported_execution(client, "854")
    snapshot = _snapshot()
    snapshot["broker_tickets"] = unusable_tickets
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "no usable tickets" in response.json()["detail"]
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.status == "SUCCESS"
        assert execution.broker_ticket == "9001"
        assert execution.lot_size == pytest.approx(0.01)
        command = db.query(models.Command).filter_by(id=cid).one()
        assert command.status == "EXECUTED_OPEN"
        conflict = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "missing_usable_broker_tickets" in conflict.payload_json
        assert "9001" not in conflict.payload_json
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_MATCHED", entity_id=cid)
            .count()
            == 0
        )


@pytest.mark.parametrize(
    "numeric_field", ["executed_price", "lot_size", "stop_loss"]
)
@pytest.mark.parametrize("bad_value", ["Infinity", "1e999"])
def test_non_finite_broker_reconciliation_fields_rejected_by_api(
    client, numeric_field, bad_value
):
    """No successful match or state update may rely on infinite broker values."""
    cid = _reported_execution(client, "855")
    snapshot = _snapshot()
    snapshot[numeric_field] = bad_value
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.broker_ticket == "9001"
        assert execution.lot_size == pytest.approx(0.01)
        assert execution.executed_price == pytest.approx(2345.0)
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_MATCHED", entity_id=cid)
            .count()
            == 0
        )


def test_non_finite_broker_recovery_cannot_create_execution(client):
    """Reject Infinity even before a first successful execution is recorded."""
    user = register_user(client, "856")
    signal = create_signal(client, _SIGNAL)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "856"},
    )
    assert approval.status_code == 200, approval.text
    command = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    assert command is not None
    cid = command["command_id"]

    snapshot = _snapshot()
    snapshot["lot_size"] = "Infinity"
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        command_row = db.query(models.Command).filter_by(id=cid).one()
        assert command_row.status == "SENT_TO_EA"
        assert (
            db.query(models.Execution).filter_by(command_id=cid).count()
            == 0
        )
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="EXECUTION_RECOVERED_FROM_BROKER_SNAPSHOT")
            .count()
            == 0
        )


@pytest.mark.parametrize("blank_entry", ["", "   ", chr(9)])
def test_mixed_blank_position_ticket_never_authorizes_snapshot(client, blank_entry):
    """A familiar position cannot hide a second unusable broker identity."""
    cid = _reported_execution(client, "857")
    snapshot = _snapshot()
    snapshot["broker_tickets"] = ["9001", blank_entry]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "blank ticket" in response.json()["detail"]
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.broker_ticket == "9001"
        assert execution.status == "SUCCESS"
        assert execution.lot_size == pytest.approx(0.01)
        command = db.query(models.Command).filter_by(id=cid).one()
        assert command.status == "EXECUTED_OPEN"
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "blank_broker_tickets" in audit.payload_json
        assert '"tickets"' not in audit.payload_json
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_MATCHED", entity_id=cid)
            .count() == 0
        )


def test_mixed_blank_ticket_cannot_create_recovered_execution(client):
    """Invalid evidence must fail before SENT_TO_EA is upgraded to executed."""
    user = register_user(client, "858")
    signal = create_signal(client, _SIGNAL)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "858"},
    )
    assert approval.status_code == 200, approval.text
    pending = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    assert pending is not None
    cid = pending["command_id"]

    snapshot = _snapshot()
    snapshot["broker_tickets"] = ["9001", "  "]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        command = db.query(models.Command).filter_by(id=cid).one()
        assert command.status == "SENT_TO_EA"
        assert db.query(models.Execution).filter_by(command_id=cid).count() == 0
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "blank_broker_tickets" in audit.payload_json
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="EXECUTION_RECOVERED_FROM_BROKER_SNAPSHOT")
            .count() == 0
        )


def test_whitespace_around_one_valid_ticket_remains_normalized(client):
    """Reject invalid entries without changing valid ticket trimming behavior."""
    cid = _reported_execution(client, "859")
    snapshot = _snapshot()
    snapshot["broker_tickets"] = [" 9001 "]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"



@pytest.mark.parametrize(
    "tickets",
    [
        ["9001", "9001"],
        ["9001", " 9001 "],
        [" 9001 ", "9001"],
    ],
    ids=["exact-duplicate", "trailing-trim-alias", "leading-trim-alias"],
)
def test_duplicate_position_ticket_does_not_match_existing_execution(client, tickets):
    """One reported ticket twice cannot impersonate two broker positions."""
    cid = _reported_execution(client, "860")
    snapshot = _snapshot()
    snapshot["broker_tickets"] = tickets
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "duplicate ticket entries" in response.json()["detail"]
    with SessionLocal() as db:
        original = db.query(models.Execution).filter_by(command_id=cid).one()
        assert original.status == "SUCCESS"
        assert original.broker_ticket == "9001"
        assert original.lot_size == pytest.approx(0.01)
        command = db.query(models.Command).filter_by(id=cid).one()
        assert command.status == "EXECUTED_OPEN"
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "duplicate_broker_tickets" in audit.payload_json
        assert '"tickets"' not in audit.payload_json
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_MATCHED", entity_id=cid)
            .count() == 0
        )


def test_duplicate_tickets_cannot_recover_unreported_broker_execution(client):
    """SENT_TO_EA stays unresolved when broker evidence repeats one identity."""
    user = register_user(client, "861")
    signal = create_signal(client, _SIGNAL)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "861"},
    )
    assert approval.status_code == 200, approval.text
    pending = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    assert pending is not None
    cid = pending["command_id"]

    snapshot = _snapshot()
    snapshot["broker_tickets"] = ["9001", "9001"]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        command = db.query(models.Command).filter_by(id=cid).one()
        assert command.status == "SENT_TO_EA"
        assert db.query(models.Execution).filter_by(command_id=cid).count() == 0
        conflict = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "duplicate_broker_tickets" in conflict.payload_json
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="EXECUTION_RECOVERED_FROM_BROKER_SNAPSHOT")
            .count() == 0
        )


def test_two_distinct_known_position_ids_still_match(client):
    """Distinct previously recorded tickets remain compatible with reconciliation."""
    cid = _reported_execution(client, "862")
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        execution.child_tickets_json = '["9001", "9002"]'
        db.commit()
    snapshot = _snapshot()
    snapshot["broker_tickets"] = ["9001", "9002"]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "matched"


@pytest.mark.parametrize(
    "invalid_ticket",
    [
        "0", "-9001", "+9001", "09001", "9e3", "ABCD",
        "\u0669\u0660\u0660\u0661",
        "18446744073709551616", "9" * 64,
    ],
    ids=[
        "zero", "negative", "explicit-plus", "leading-zero",
        "exponent", "alphabetic", "unicode-digits", "uint64-overflow",
        "overlong",
    ],
)
@pytest.mark.parametrize(
    "include_valid_ticket", [False, True],
    ids=["invalid-alone", "valid-plus-invalid"],
)
def test_fabricated_mt5_position_tickets_never_recover_execution(
    client, invalid_ticket, include_valid_ticket
):
    """Broker-free: an MT5 position ticket must be canonical decimal uint64.

    Neither an invalid-only nor a mixed snapshot can turn an unresolved
    command into a recorded SUCCESS or forge a matched broker identity.
    """
    user = register_user(client, "863")
    signal = create_signal(client, _SIGNAL)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "863"},
    )
    assert approval.status_code == 200, approval.text
    pending = client.get(
        "/commands/pending",
        params={"user_id": user["id"]}, headers=EA_HEADERS,
    ).json()["command"]
    assert pending is not None
    cid = pending["command_id"]

    snapshot = _snapshot()
    snapshot["broker_tickets"] = (
        ["9001", invalid_ticket] if include_valid_ticket else [invalid_ticket]
    )
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "invalid MT5 ticket" in response.json()["detail"]
    with SessionLocal() as db:
        command = db.query(models.Command).filter_by(id=cid).one()
        assert command.status == "SENT_TO_EA"
        assert db.query(models.Execution).filter_by(command_id=cid).count() == 0
        audit = (
            db.query(models.AuditLog)
            .filter_by(event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid)
            .one()
        )
        assert "invalid_mt5_broker_tickets" in audit.payload_json
        assert '"tickets"' not in audit.payload_json
        assert (
            db.query(models.AuditLog)
            .filter_by(event_type="EXECUTION_RECOVERED_FROM_BROKER_SNAPSHOT")
            .count() == 0
        )


def test_canonical_mt5_uint64_ticket_boundary_remains_accepted(client):
    """Synthetic positive boundary, NOT live MT5 ownership or fill evidence."""
    user = register_user(client, "864")
    signal = create_signal(client, _SIGNAL)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "864"},
    )
    assert approval.status_code == 200, approval.text
    pending = client.get(
        "/commands/pending",
        params={"user_id": user["id"]}, headers=EA_HEADERS,
    ).json()["command"]
    assert pending is not None
    cid = pending["command_id"]
    max_uint64_ticket = "18446744073709551615"
    snapshot = _snapshot()
    snapshot["broker_tickets"] = [max_uint64_ticket]
    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=snapshot, headers=EA_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "recovered"
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.broker_ticket == max_uint64_ticket
        assert db.query(models.Command).filter_by(id=cid).one().status == "EXECUTED_OPEN"


@pytest.mark.parametrize(
    "stored_primary",
    ["", "0", "09001", "+9001", "9001 ", "18446744073709551616"],
    ids=["empty", "zero", "padded", "signed", "whitespace", "uint64-overflow"],
)
def test_corrupt_stored_primary_cannot_be_masked_by_valid_child(
    client, stored_primary
):
    """An otherwise matching child must not validate a corrupted primary ID."""
    cid = _reported_execution(client, "865")
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        execution.broker_ticket = stored_primary
        execution.child_tickets_json = '["9001"]'
        db.commit()

    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(), headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "stored_ticket_payload" in response.json()["detail"]
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.status == "SUCCESS"
        assert execution.broker_ticket == stored_primary
        assert execution.child_tickets_json == '["9001"]'
        assert execution.lot_size == pytest.approx(0.01)
        assert execution.executed_price == pytest.approx(2345.0)
        audit = db.query(models.AuditLog).filter_by(
            event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid
        ).one()
        assert "stored_ticket_payload" in audit.payload_json


@pytest.mark.parametrize(
    "stored_children",
    [
        "", '["9001", "09001"]', '["9001", "0"]',
        '["9001", "9001"]', '["9001", "9001 "]',
        '["9001", "+9002"]', '["9001", "18446744073709551616"]',
    ],
    ids=[
        "invalid-json-empty", "padded", "zero", "duplicate", "whitespace",
        "signed", "uint64-overflow",
    ],
)
def test_corrupt_stored_child_cannot_be_masked_by_valid_primary(
    client, stored_children
):
    """A matching primary must not turn an invalid child array into a MATCH."""
    cid = _reported_execution(client, "866")
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        execution.child_tickets_json = stored_children
        db.commit()

    response = client.post(
        f"/commands/{cid}/reconcile_open_position",
        json=_snapshot(), headers=EA_HEADERS,
    )
    assert response.status_code == 409, response.text
    assert "stored_ticket_payload" in response.json()["detail"]
    with SessionLocal() as db:
        execution = db.query(models.Execution).filter_by(command_id=cid).one()
        assert execution.status == "SUCCESS"
        assert execution.broker_ticket == "9001"
        assert execution.child_tickets_json == stored_children
        assert execution.lot_size == pytest.approx(0.01)
        assert execution.executed_price == pytest.approx(2345.0)
        audit = db.query(models.AuditLog).filter_by(
            event_type="BROKER_RECONCILIATION_CONFLICT", entity_id=cid
        ).one()
        assert "stored_ticket_payload" in audit.payload_json
