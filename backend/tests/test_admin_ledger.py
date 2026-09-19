"""Tests for the honest read-only performance ledger."""
from __future__ import annotations

from app import models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def test_ledger_requires_admin(client):
    assert client.get("/admin/ledger").status_code == 403


def test_ledger_lists_pending_signal(client):
    create_signal(client, VALID)
    response = client.get("/admin/ledger", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    row = response.json()["ledger"][0]
    assert row["symbol"] == "XAUUSD"
    assert row["result_status"] == "PENDING"


def test_bare_fully_closed_is_not_fabricated_as_win(client):
    user = register_user(client, "711")
    sig = create_signal(client, VALID)
    decision = client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "711"},
    ).json()
    command = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    cid = command["command_id"]
    assert cid == decision["command_id"]

    execution = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "SUCCESS",
            "executed_price": 2345.0,
            "lot_size": 0.04,
            "initial_stop_loss": 2343.0,
        },
        headers=EA_HEADERS,
    )
    assert execution.status_code == 200
    closed = client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "FULLY_CLOSED", "result": "SUCCESS"},
        headers=EA_HEADERS,
    )
    assert closed.status_code == 200

    body = client.get("/admin/ledger", headers=ADMIN_HEADERS).json()
    row = next(item for item in body["ledger"] if item["command_id"] == cid)
    assert row["result_status"] == "CLOSED_UNATTRIBUTED"
    assert row["r_result"] is None


def test_stop_out_remains_visible_as_loss(client):
    user = register_user(client, "712")
    sig = create_signal(client, VALID)
    decision = client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": "712"},
    ).json()
    command = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    ).json()["command"]
    cid = decision["command_id"]
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
    client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "STOP_LOSS_HIT", "result": "SUCCESS", "price": 2343.0},
        headers=EA_HEADERS,
    )

    db = SessionLocal()
    try:
        row = (
            db.query(models.PerformanceLedger)
            .filter(models.PerformanceLedger.command_id == cid)
            .one()
        )
        assert row.result_status == "STOPPED_OUT"
        assert row.r_result == -1.0
    finally:
        db.close()
