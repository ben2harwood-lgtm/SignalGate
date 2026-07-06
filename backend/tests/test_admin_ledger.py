"""Tests for the read-only /admin/ledger surface.

The ledger is the product's core artifact — the demo shows it live, so it must be
readable, admin-gated, and must expose losses as losses (never hide a stop-out).
"""
from __future__ import annotations

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def test_ledger_requires_admin(client):
    resp = client.get("/admin/ledger")
    assert resp.status_code == 403


def test_ledger_lists_pending_signal_row(client):
    create_signal(client, VALID)
    body = client.get("/admin/ledger", headers=ADMIN_HEADERS).json()
    assert body["count"] == 1
    row = body["ledger"][0]
    assert row["symbol"] == "XAUUSD"
    assert row["result_status"] == "PENDING"


def test_ledger_shows_stop_out_as_a_loss(client):
    """A stopped-out trade must appear in the record as STOPPED_OUT — the honesty
    property the whole product exists to guarantee."""
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
    client.post(
        f"/commands/{cid}/management_event",
        json={"event_type": "STOP_LOSS_HIT", "result": "SUCCESS"},
        headers=EA_HEADERS,
    )

    body = client.get("/admin/ledger", headers=ADMIN_HEADERS).json()
    row = next(r for r in body["ledger"] if r["command_id"] == cid)
    assert row["result_status"] == "STOPPED_OUT"
    assert row["r_result"] is not None and row["r_result"] < 0
