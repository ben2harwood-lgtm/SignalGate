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
