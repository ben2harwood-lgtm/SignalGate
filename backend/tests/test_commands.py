"""Command polling, execution, and management event tests."""
from __future__ import annotations

from .conftest import EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _approve(client, telegram_id="123"):
    register_user(client, telegram_id)
    sig = create_signal(client, VALID)
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": telegram_id}
    ).json()
    return resp


def _user_id(client, telegram_id="123"):
    # registration returns id
    u = register_user(client, telegram_id)
    return u["id"]


def test_pending_command_returned_once(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})

    r1 = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()
    assert r1["command"] is not None
    assert r1["command"]["symbol"] == "XAUUSD"
    assert len(r1["command"]["take_profits"]) == 3

    # Second poll should not return the same command (now SENT_TO_EA).
    r2 = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()
    assert r2["command"] is None


def test_pending_requires_ea_key(client):
    resp = client.get("/commands/pending", params={"user_id": "USER-000001"})
    assert resp.status_code == 401


def test_execution_success_updates_status(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    client.post(f"/commands/{cid}/received", json={}, headers=EA_HEADERS)
    resp = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "SUCCESS",
            "broker_ticket": "100",
            "child_tickets_json": "[100,101,102]",
            "executed_symbol": "XAUUSD",
            "executed_direction": "BUY",
            "executed_price": 2345.0,
            "lot_size": 0.04,
            "initial_stop_loss": 2343.0,
        },
        headers=EA_HEADERS,
    )
    assert resp.status_code == 200

    status = client.get("/admin/status", headers={"X-Admin-Id": "999"}).json()
    assert status["counts"]["executions"] == 1


def test_execution_failed_recorded(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    cid = cmd["command_id"]

    resp = client.post(
        f"/commands/{cid}/execution",
        json={
            "status": "FAILED",
            "error_code": "SPREAD_TOO_HIGH",
            "error_message": "Spread above max",
        },
        headers=EA_HEADERS,
    )
    assert resp.status_code == 200


def test_management_events_update_status(client):
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
    for event in ["TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS", "TP3_CLOSE_SUCCESS",
                  "FULLY_CLOSED"]:
        resp = client.post(
            f"/commands/{cid}/management_event",
            json={"event_type": event, "result": "SUCCESS"},
            headers=EA_HEADERS,
        )
        assert resp.status_code == 200

    status = client.get("/admin/status", headers={"X-Admin-Id": "999"}).json()
    assert status["counts"]["management_events"] == 4
