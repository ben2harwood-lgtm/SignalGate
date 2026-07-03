"""Command-lifecycle integrity: state-machine guards, EA-report ownership,
stale-command recovery, and the truthful pause-blocked message.

Covers findings P1-2, P1-3/P1-7, P1-5, P1-15, P2-1/P2-2/P2-6, P2-8.
"""
from __future__ import annotations

import datetime as dt

from app import models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _approve_and_poll(client, telegram_id="123"):
    user = register_user(client, telegram_id)
    sig = create_signal(client, VALID)
    client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": telegram_id}
    )
    cmd = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    return user, sig, cmd["command_id"]


def _command_status(cid):
    db = SessionLocal()
    try:
        return db.get(models.Command, cid).status
    finally:
        db.close()


# --- Execution state machine (P1-2) --------------------------------------

def test_execution_rejected_unless_sent_to_ea(client):
    """An execution report on a never-polled PENDING command is refused."""
    register_user(client, "123")
    sig = create_signal(client, VALID)
    cmd = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    cid = cmd["command_id"]  # status PENDING, never handed to an EA

    resp = client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04,
              "initial_stop_loss": 2343.0},
        headers=EA_HEADERS,
    )
    assert resp.status_code == 409
    assert _command_status(cid) == "PENDING"


def test_duplicate_execution_report_rejected(client):
    """A second execution report cannot overwrite the first / add a row."""
    user, sig, cid = _approve_and_poll(client)
    ok = client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04,
              "initial_stop_loss": 2343.0},
        headers=EA_HEADERS,
    )
    assert ok.status_code == 200
    dup = client.post(
        f"/commands/{cid}/execution",
        json={"status": "FAILED", "error_code": "X"},
        headers=EA_HEADERS,
    )
    assert dup.status_code == 409
    assert _command_status(cid) == "EXECUTED_OPEN"
    status = client.get("/admin/status", headers=ADMIN_HEADERS).json()
    assert status["counts"]["executions"] == 1


# --- Management-event state machine (P1-5) -------------------------------

def test_stale_open_event_cannot_reopen_closed_command(client):
    """A stray OPENED after FULLY_CLOSED must not reopen the command."""
    user, sig, cid = _approve_and_poll(client)
    client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04,
              "initial_stop_loss": 2343.0},
        headers=EA_HEADERS,
    )
    for ev in ["TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS", "TP3_CLOSE_SUCCESS"]:
        client.post(f"/commands/{cid}/management_event",
                    json={"event_type": ev, "result": "SUCCESS"}, headers=EA_HEADERS)
    assert _command_status(cid) == "FULLY_CLOSED"

    # Stray OPENED afterwards: recorded (200) but status stays FULLY_CLOSED.
    resp = client.post(f"/commands/{cid}/management_event",
                       json={"event_type": "OPENED", "result": "SUCCESS"},
                       headers=EA_HEADERS)
    assert resp.status_code == 200
    assert _command_status(cid) == "FULLY_CLOSED"


def test_pending_command_cannot_jump_to_fully_closed(client):
    """A management event on a never-executed command must not corrupt it."""
    register_user(client, "123")
    sig = create_signal(client, VALID)
    cid = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()["command_id"]

    resp = client.post(f"/commands/{cid}/management_event",
                       json={"event_type": "TP3_CLOSE_SUCCESS", "result": "SUCCESS"},
                       headers=EA_HEADERS)
    assert resp.status_code == 200  # event recorded...
    assert _command_status(cid) == "PENDING"  # ...but status untouched

    led = _ledger_status(sig["id"])
    assert led not in {"TP3_HIT", "TP2_HIT", "TP1_HIT"}


def _ledger_status(signal_id):
    db = SessionLocal()
    try:
        return (
            db.query(models.PerformanceLedger)
            .filter(models.PerformanceLedger.signal_id == signal_id)
            .first()
            .result_status
        )
    finally:
        db.close()


# --- Stale SENT_TO_EA recovery + admin reset (P1-15, P2-1/P2-6) ----------

def test_stuck_sent_to_ea_times_out(client):
    """A SENT_TO_EA command past expiry+grace is failed, not stranded."""
    user, sig, cid = _approve_and_poll(client)
    assert _command_status(cid) == "SENT_TO_EA"

    # Force the command past its expiry window.
    db = SessionLocal()
    try:
        cmd = db.get(models.Command, cid)
        cmd.expires_at = dt.datetime.utcnow() - dt.timedelta(minutes=10)
        db.commit()
    finally:
        db.close()

    # A subsequent poll sweeps it.
    client.get("/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS)
    assert _command_status(cid) == "FAILED"


def test_admin_reset_returns_command_to_pending(client):
    user, sig, cid = _approve_and_poll(client)
    assert _command_status(cid) == "SENT_TO_EA"

    resp = client.post(f"/admin/commands/{cid}/reset", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    assert _command_status(cid) == "PENDING"

    # And it can be delivered again.
    again = client.get(
        "/commands/pending", params={"user_id": user["id"]}, headers=EA_HEADERS
    ).json()["command"]
    assert again is not None and again["command_id"] == cid


def test_admin_reset_refuses_live_trade(client):
    user, sig, cid = _approve_and_poll(client)
    client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04,
              "initial_stop_loss": 2343.0},
        headers=EA_HEADERS,
    )
    assert _command_status(cid) == "EXECUTED_OPEN"
    resp = client.post(f"/admin/commands/{cid}/reset", headers=ADMIN_HEADERS)
    assert resp.status_code == 409  # cannot reset a live/complete trade


# --- Truthful pause-blocked message + resume retry (P2-2) ----------------

def test_yes_during_pause_then_resume_creates_command(client):
    register_user(client, "123")
    client.post("/admin/pause", headers=ADMIN_HEADERS)
    sig = create_signal(client, VALID)
    blocked = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert blocked["result"] == "TRADING_PAUSED"
    assert blocked["command_id"] is None

    client.post("/admin/resume", headers=ADMIN_HEADERS)
    retry = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    # The earlier YES is honoured now -- NOT a misleading "already approved".
    assert retry["result"] == "APPROVED"
    assert retry["command_id"] is not None


def test_yes_during_pause_not_misreported_as_already_approved(client):
    register_user(client, "123")
    client.post("/admin/pause", headers=ADMIN_HEADERS)
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})
    # Still paused: a second YES must not claim "already approved".
    again = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert again["result"] == "TRADING_PAUSED"
    assert again["command_id"] is None


# --- Empty EA key fails closed (P2-8) ------------------------------------

def test_wrong_ea_key_rejected(client):
    resp = client.get(
        "/commands/pending",
        params={"user_id": "USER-000001"},
        headers={"X-EA-API-Key": "wrong"},
    )
    assert resp.status_code == 401


# --- Cross-tenant EA reporting blocked in hosted mode (P1-3/P1-7) --------

def test_execution_report_scoped_to_owning_license(client, monkeypatch):
    from app.config import get_settings

    register_user(client, "123")
    register_user(client, "456")
    la = client.post(
        "/admin/users/123/issue_license", headers=ADMIN_HEADERS
    ).json()["license_key"]
    lb = client.post(
        "/admin/users/456/issue_license", headers=ADMIN_HEADERS
    ).json()["license_key"]

    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})

    # Turn on hosted multi-tenant enforcement.
    monkeypatch.setattr(get_settings(), "require_license", True)

    cmd = client.get(
        "/commands/pending", params={"license_key": la}, headers=EA_HEADERS
    ).json()["command"]
    assert cmd is not None
    cid = cmd["command_id"]

    # Customer B's EA (same shared key) posting to A's command -> 403.
    forged = client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "license_key": lb, "executed_price": 2345.0,
              "lot_size": 0.04, "initial_stop_loss": 2343.0},
        headers=EA_HEADERS,
    )
    assert forged.status_code == 403
    assert _command_status(cid) == "SENT_TO_EA"  # untouched

    # A's own EA reports fine.
    ok = client.post(
        f"/commands/{cid}/execution",
        json={"status": "SUCCESS", "license_key": la, "executed_price": 2345.0,
              "lot_size": 0.04, "initial_stop_loss": 2343.0},
        headers=EA_HEADERS,
    )
    assert ok.status_code == 200
