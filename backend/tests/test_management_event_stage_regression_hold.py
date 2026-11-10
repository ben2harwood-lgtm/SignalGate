"""Offline regression witness for out-of-order EA management-event stages.

This is a release HOLD test: it records an observed backend state regression
without authorizing EA changes, broker activity, or external acceptance.
"""
from __future__ import annotations

import json

import pytest

from app import crud, models
from app.database import SessionLocal
from .conftest import EA_HEADERS, create_signal, register_user


def test_late_tp1_success_cannot_regress_committed_tp2_stage(client, monkeypatch):
    """A second, differently keyed TP1 receipt must not undo an advanced TP2.

    Stage is part of management-event idempotency identity, so a delayed TP1
    callback with its own stage is not filtered as an exact duplicate.
    Assert that state, ledger result/R and the advancing-audit flag remain
    consistent while the distinct late receipt is retained.
    Synthetic SQLite/PostgreSQL records only; never a broker scenario.
    """
    owner = register_user(client, "990091")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990091"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    polled = client.get(
        "/commands/pending",
        params={"user_id": owner["id"]},
        headers=EA_HEADERS,
    )
    assert polled.status_code == 200, polled.text
    command = polled.json()["command"]
    assert command is not None
    command_id = command["command_id"]

    executed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    # EA emits TP-close receipts before the *separate* stop-loss move result.
    # Customer-facing text must not declare that SL move complete yet.
    from app.routes import commands as command_routes

    stage_notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda *args, **kwargs: stage_notifications.append((args, kwargs)),
    )

    for event_type, stage in (
        ("TP1_CLOSE_SUCCESS", "TP1_DONE"),
        ("TP2_CLOSE_SUCCESS", "TP2_DONE"),
    ):
        response = client.post(
            f"/commands/{command_id}/management_event",
            json={"event_type": event_type, "stage": stage, "result": "SUCCESS"},
            headers=EA_HEADERS,
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ok"

    assert len(stage_notifications) == 2
    for level, (args, _kwargs) in zip(("TP1", "TP2"), stage_notifications):
        message = args[1]
        assert f"{level} close reported" in message
        assert "Stop-loss change not yet confirmed" in message
        assert "SL moved" not in message

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "PARTIAL_TP2_DONE"
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == "TP2_HIT"
        assert ledger_row.r_result == pytest.approx(6.5)

    # An accepted stale TP1 receipt must not send a misleading second
    # "TP1 hit / SL moved" notification after TP2 has completed.
    late_notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda *args, **kwargs: late_notifications.append((args, kwargs)),
    )

    late = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": "TP1_CLOSE_SUCCESS",
            "stage": "TP1_LATE_RETRY",
            "result": "SUCCESS",
        },
        headers=EA_HEADERS,
    )
    assert late.status_code == 200, late.text
    assert late.json()["status"] == "ok"
    assert not late_notifications, "Stale TP1 receipt must not notify after TP2"

    with SessionLocal() as session:
        stored = crud.get_command(session, command_id)
        assert stored is not None
        assert stored.status == "PARTIAL_TP2_DONE"
        events = (
            session.query(models.TradeManagementEvent)
            .filter(models.TradeManagementEvent.command_id == command_id)
            .order_by(models.TradeManagementEvent.id)
            .all()
        )
        assert len(events) == 3, "All three distinct receipts must be persisted"
        assert sorted(event.event_type for event in events) == [
            "TP1_CLOSE_SUCCESS", "TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS"
        ]
        late_event = next(event for event in events if event.stage == "TP1_LATE_RETRY")
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == "TP2_HIT"
        assert ledger_row.r_result == pytest.approx(6.5)
        audit = session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT",
            entity_type="management_event",
            entity_id=late_event.id,
        ).one()
        assert json.loads(audit.payload_json)["state_advanced"] is False

    # The already stored late receipt still obeys normal idempotency.
    repeated = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": "TP1_CLOSE_SUCCESS",
            "stage": "TP1_LATE_RETRY",
            "result": "SUCCESS",
        },
        headers=EA_HEADERS,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "duplicate_ignored"


@pytest.mark.parametrize(
    ("breakeven_result", "tp1_result"),
    [("SUCCESS", "FAILED"), ("FAILED", "SUCCESS")],
)
def test_stop_loss_move_messages_follow_matching_ea_receipts(
    client, monkeypatch, breakeven_result, tp1_result
):
    """A TP close is not SL proof; current-stage SL outcomes notify once.

    Late results from an earlier/closed stage remain audited but do not imply
    new protection. All inputs and notifications are synthetic/offline.
    """
    owner = register_user(client, "990092")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990092"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    pending = client.get(
        "/commands/pending",
        params={"user_id": owner["id"]},
        headers=EA_HEADERS,
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]
    executed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    from app.routes import commands as command_routes

    messages = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda _chat_id, message: messages.append(message),
    )

    def receipt(event_type, stage, result):
        response = client.post(
            f"/commands/{command_id}/management_event",
            json={"event_type": event_type, "stage": stage, "result": result},
            headers=EA_HEADERS,
        )
        assert response.status_code == 200, response.text
        return response.json()["status"]

    assert receipt("TP1_CLOSE_SUCCESS", "TP1_DONE", "SUCCESS") == "ok"
    assert len(messages) == 1
    assert "not yet confirmed" in messages[-1]
    first_type = f"SL_MOVE_BREAKEVEN_{breakeven_result}"
    assert receipt(first_type, "TP1_DONE", breakeven_result) == "ok"
    assert len(messages) == 2
    if breakeven_result == "FAILED":
        assert "FAILED" in messages[-1] and "Protection not confirmed" in messages[-1]
    else:
        assert "Demo EA reported" in messages[-1]
        assert "not independently confirmed" in messages[-1]
        assert "succeeded" not in messages[-1]
    assert receipt(first_type, "TP1_DONE", breakeven_result) == "duplicate_ignored"
    assert len(messages) == 2, "Duplicate management receipt must not notify twice"

    assert receipt("TP2_CLOSE_SUCCESS", "TP2_DONE", "SUCCESS") == "ok"
    assert len(messages) == 3
    assert "not yet confirmed" in messages[-1]
    second_type = f"SL_MOVE_TP1_{tp1_result}"
    assert receipt(second_type, "TP2_DONE", tp1_result) == "ok"
    assert len(messages) == 4
    if tp1_result == "FAILED":
        assert "FAILED" in messages[-1] and "Protection not confirmed" in messages[-1]
    else:
        assert "Demo EA reported" in messages[-1]
        assert "not independently confirmed" in messages[-1]
        assert "succeeded" not in messages[-1]

    opposite_breakeven = "FAILED" if breakeven_result == "SUCCESS" else "SUCCESS"
    assert receipt(
        f"SL_MOVE_BREAKEVEN_{opposite_breakeven}",
        "TP1_LATE_SL_RECEIPT",
        opposite_breakeven,
    ) == "ok"
    assert len(messages) == 4, "Stale TP1 stop-loss receipt must not notify after TP2"

    assert receipt("TP3_CLOSE_SUCCESS", "TP3_DONE", "SUCCESS") == "ok"
    assert len(messages) == 5
    assert "Demo EA reports TP3 child closed" in messages[-1]
    assert "not independently confirmed" in messages[-1]
    assert "check demo terminal" in messages[-1]
    opposite_tp1 = "FAILED" if tp1_result == "SUCCESS" else "SUCCESS"
    assert receipt(
        f"SL_MOVE_TP1_{opposite_tp1}", "TP2_LATE_SL_RECEIPT", opposite_tp1
    ) == "ok"
    assert len(messages) == 5, "Closed command must not notify an old SL move"

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "FULLY_CLOSED"
        events = session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id
        ).all()
        assert len(events) == 7, "Distinct late receipts are still persisted for audit"


@pytest.mark.parametrize(
    ("event_type", "result"),
    [
        ("TP1_CLOSE_SUCCESS", "FAILED"),
        ("TP1_CLOSE_SUCCESS", "PENDING"),
        ("TP2_CLOSE_SUCCESS", "FAILED"),
        ("TP3_CLOSE_SUCCESS", "FAILED"),
        # Terminal close/stop callbacks have no suffix but must not turn
        # a failed/pending EA report into a broker-success milestone.
        ("STOP_LOSS_HIT", "FAILED"),
        ("STOP_LOSS_HIT", "PENDING"),
        ("FULLY_CLOSED", "FAILED"),
        ("FULLY_CLOSED", "PENDING"),
        ("SL_MOVE_BREAKEVEN_SUCCESS", "FAILED"),
        ("SL_MOVE_TP1_FAILED", "SUCCESS"),
    ],
)
def test_explicitly_contradictory_management_outcomes_are_rejected(
    client, monkeypatch, event_type, result
):
    """Bad EA self-reports must not create a TP milestone, audit or notification.

    This is synthetic evidence only; no actual broker has confirmed a position.
    Missing optional result is still accepted for legacy report compatibility.
    """
    owner = register_user(client, "990093")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990093"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    pending = client.get(
        "/commands/pending",
        params={"user_id": owner["id"]},
        headers=EA_HEADERS,
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]
    executed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    from app.routes import commands as command_routes

    notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda *args, **kwargs: notifications.append((args, kwargs)),
    )
    rejected = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": event_type,
            "stage": "CONTRADICTORY_RESULT",
            "result": result,
        },
        headers=EA_HEADERS,
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"] == "Management event type and result disagree"
    assert notifications == []

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "EXECUTED_OPEN"
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == "EXECUTED_OPEN"
        assert ledger_row.r_result is None
        assert session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id
        ).count() == 0
        assert session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT"
        ).count() == 0, "Rejected report must not fabricate a management audit"

    # A malformed first attempt cannot poison the idempotency key of a later
    # corrected callback for the same event/stage.
    corrected_result = "FAILED" if event_type.endswith("_FAILED") else "SUCCESS"
    corrected = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": event_type,
            "stage": "CONTRADICTORY_RESULT",
            "result": corrected_result,
        },
        headers=EA_HEADERS,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["status"] == "ok"
    if event_type in {"TP3_CLOSE_SUCCESS", "STOP_LOSS_HIT", "FULLY_CLOSED"}:
        assert len(notifications) == 1
        message = notifications[0][0][1]
        assert "Demo EA reports" in message
        assert "not independently confirmed" in message
        assert "check demo terminal" in message
    with SessionLocal() as session:
        assert session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id
        ).count() == 1
        assert session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT"
        ).count() == 1, "Corrected report has exactly one management audit"
