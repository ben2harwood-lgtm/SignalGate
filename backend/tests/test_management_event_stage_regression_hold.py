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

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "PARTIAL_TP2_DONE"
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == "TP2_HIT"
        assert ledger_row.r_result == pytest.approx(6.5)

    # An accepted stale TP1 receipt must not send a misleading second
    # "TP1 hit / SL moved" notification after TP2 has completed.
    from app.routes import commands as command_routes

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
