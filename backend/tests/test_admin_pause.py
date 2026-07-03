"""Admin pause / resume tests."""
from __future__ import annotations

from app import models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _command_count():
    db = SessionLocal()
    try:
        return db.query(models.Command).count()
    finally:
        db.close()


def test_pause_blocks_command_creation(client):
    register_user(client, "123")
    client.post("/admin/pause", headers=ADMIN_HEADERS)

    sig = create_signal(client, VALID)
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert resp["result"] == "TRADING_PAUSED"
    assert _command_count() == 0


def test_resume_restores_approvals(client):
    register_user(client, "123")
    client.post("/admin/pause", headers=ADMIN_HEADERS)
    client.post("/admin/resume", headers=ADMIN_HEADERS)

    sig = create_signal(client, VALID)
    resp = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert resp["result"] == "APPROVED"
    assert _command_count() == 1


def test_admin_endpoints_require_admin(client):
    resp = client.post("/admin/pause")
    assert resp.status_code == 403
