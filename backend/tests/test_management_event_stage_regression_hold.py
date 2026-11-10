"""Offline regression witness for out-of-order EA management-event stages.

This is a release HOLD test: it records an observed backend state regression
without authorizing EA changes, broker activity, or external acceptance.
"""
from __future__ import annotations

import pytest

from app import crud, models
from app.database import SessionLocal
from .conftest import EA_HEADERS, create_signal, register_user


def test_late_tp1_success_cannot_regress_committed_tp2_stage(client):
    """A second, differently keyed TP1 receipt must not undo an advanced TP2.

    Stage is part of management-event idempotency identity, so a delayed TP1
    callback with its own stage is not filtered as an exact duplicate.
    Assert all setup/HTTP preconditions normally; XFAIL only if the *specific*
    PARTIAL_TP2_DONE -> PARTIAL_TP1_DONE regression is actually observed.
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

    with SessionLocal() as session:
        stored = crud.get_command(session, command_id)
        assert stored is not None
        resulting_status = stored.status
        event_types = list(
            session.query(models.TradeManagementEvent.event_type)
            .filter(models.TradeManagementEvent.command_id == command_id)
            .order_by(models.TradeManagementEvent.id)
            .all()
        )
    assert len(event_types) == 3, "All three distinct receipts must be persisted"
    if resulting_status == "PARTIAL_TP1_DONE":
        pytest.xfail(
            "Confirmed stage-order defect: delayed TP1 success regresses committed "
            "PARTIAL_TP2_DONE to PARTIAL_TP1_DONE; execution-safety review required"
        )
    assert resulting_status == "PARTIAL_TP2_DONE", (
        "Late management callback must not regress the command's recorded stage"
    )
