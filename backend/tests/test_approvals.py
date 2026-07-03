"""Approval / command idempotency tests."""
from __future__ import annotations

from app import crud, models
from app.database import SessionLocal

from .conftest import create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _command_count():
    db = SessionLocal()
    try:
        return db.query(models.Command).count()
    finally:
        db.close()


def test_yes_creates_one_command(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "APPROVED"
    assert data["command_id"] is not None
    assert _command_count() == 1


def test_duplicate_yes_no_second_command(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    first = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    second = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert second["duplicate"] is True
    assert second["result"] == "ALREADY_APPROVED"
    assert second["command_id"] == first["command_id"]
    assert _command_count() == 1


def test_no_creates_no_command(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    resp = client.post(
        f"/signals/{sig['id']}/reject", json={"telegram_user_id": "123"}
    ).json()
    assert resp["result"] == "REJECTED"
    assert resp["command_id"] is None
    assert _command_count() == 0


def test_reject_after_approve_blocked(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    resp = client.post(
        f"/signals/{sig['id']}/reject", json={"telegram_user_id": "123"}
    ).json()
    # First decision (YES) wins; no cancellation.
    assert resp["duplicate"] is True
    assert resp["result"] == "ALREADY_APPROVED"
    assert _command_count() == 1


def test_approve_after_reject_blocked(client):
    register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/reject", json={"telegram_user_id": "123"})
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert resp["duplicate"] is True
    assert resp["result"] == "ALREADY_REJECTED"
    assert _command_count() == 0


def test_approve_unregistered_user(client):
    sig = create_signal(client, VALID)
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "nope"}
    ).json()
    assert resp["result"] == "USER_NOT_FOUND"


def test_approve_rejected_signal_creates_no_command(client):
    register_user(client, "123")
    sig = create_signal(client, "random nonsense no signal here")
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert resp["result"] == "PARSER_REJECTED"
    assert _command_count() == 0
