"""Signal/command expiry tests."""
from __future__ import annotations

import datetime as dt

from app import models
from app.database import SessionLocal

from .conftest import EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _expire_signal(signal_id):
    db = SessionLocal()
    try:
        sig = db.get(models.Signal, signal_id)
        sig.expires_at = dt.datetime.utcnow() - dt.timedelta(minutes=1)
        db.commit()
    finally:
        db.close()


def _expire_command(command_id):
    db = SessionLocal()
    try:
        cmd = db.get(models.Command, command_id)
        cmd.expires_at = dt.datetime.utcnow() - dt.timedelta(minutes=1)
        db.commit()
    finally:
        db.close()


def test_expired_signal_cannot_be_approved(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    _expire_signal(sig["id"])
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert resp["result"] == "SIGNAL_EXPIRED"
    assert resp["command_id"] is None


def test_expired_command_not_returned_to_ea(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    cmd_resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    _expire_command(cmd_resp["command_id"])

    resp = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()
    assert resp["command"] is None
