"""Performance ledger tests."""
from __future__ import annotations

from app import models
from app.database import SessionLocal

from .conftest import EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _ledger_for_signal(signal_id):
    db = SessionLocal()
    try:
        return (
            db.query(models.PerformanceLedger)
            .filter(models.PerformanceLedger.signal_id == signal_id)
            .first()
        )
    finally:
        db.close()


def test_signal_creates_ledger_row(client):
    sig = create_signal(client, VALID)
    led = _ledger_for_signal(sig["id"])
    assert led is not None
    assert led.result_status == "PENDING"
    assert led.symbol == "XAUUSD"


def test_rejected_signal_ledger_rejected(client):
    sig = create_signal(client, "garbage no signal")
    led = _ledger_for_signal(sig["id"])
    assert led.result_status == "REJECTED"


def test_user_rejection_updates_ledger(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/reject", json={"telegram_user_id": "123"})
    led = _ledger_for_signal(sig["id"])
    assert led.result_status == "REJECTED"


def test_command_creation_updates_ledger(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    led = _ledger_for_signal(sig["id"])
    assert led.result_status == "APPROVED_NOT_EXECUTED"
    assert led.command_id is not None


def test_execution_and_tp_events_update_ledger(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "SUCCESS",
            "executed_price": 2345.0,
            "lot_size": 0.04,
            "initial_stop_loss": 2343.0,
        },
        headers=EA_HEADERS,
    )
    led = _ledger_for_signal(sig["id"])
    assert led.result_status == "EXECUTED_OPEN"
    assert led.entry_price == 2345.0

    client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "TP1_CLOSE_SUCCESS", "result": "SUCCESS"},
        headers=EA_HEADERS,
    )
    led = _ledger_for_signal(sig["id"])
    assert led.result_status == "TP1_HIT"
    # R should be positive: (2353-2345)/(2345-2343) = 8/2 = 4.0
    assert led.r_result is not None and led.r_result > 0

    client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "TP3_CLOSE_SUCCESS", "result": "SUCCESS"},
        headers=EA_HEADERS,
    )
    led = _ledger_for_signal(sig["id"])
    assert led.result_status == "TP3_HIT"
