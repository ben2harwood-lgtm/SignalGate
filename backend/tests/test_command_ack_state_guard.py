"""HTTP/state regression tests for the pre-broker EA acknowledgement gate.

All requests are local/synthetic; passing tests do NOT establish actual MT5
DEMO acceptance or resolve PR #60's acknowledgement-outage recovery finding.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
import time

import pytest

from app import models
from app.database import SessionLocal

from .conftest import EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _approved_command(client):
    user = register_user(client, "123")
    signal = create_signal(client, VALID)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "123"},
    )
    assert approval.status_code == 200
    command_id = approval.json()["command_id"]
    assert command_id
    return user["id"], command_id


def _claim_command(client, user_id, command_id):
    response = client.get(
        "/commands/pending", params={"user_id": user_id}, headers=EA_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["command"]["command_id"] == command_id


def _set_command(command_id, *, status=None, expires_at=None):
    with SessionLocal() as db:
        command = db.get(models.Command, command_id)
        assert command is not None
        if status is not None:
            command.status = status
        if expires_at is not None:
            command.expires_at = expires_at
        db.commit()


def _status(command_id):
    with SessionLocal() as db:
        return db.get(models.Command, command_id).status


def _ack(client, command_id, headers=EA_HEADERS):
    return client.post(
        f"/commands/{command_id}/received", json={}, headers=headers
    )


def test_ack_rejects_unclaimed_command_before_poll(client):
    _user, command_id = _approved_command(client)
    assert _status(command_id) == "PENDING"
    denied = _ack(client, command_id)
    assert denied.status_code == 409
    assert _status(command_id) == "PENDING"


def test_ack_accepts_only_current_claim_and_is_retryable_before_execution(client):
    user_id, command_id = _approved_command(client)
    _claim_command(client, user_id, command_id)
    first = _ack(client, command_id)
    second = _ack(client, command_id)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "received"
    assert _status(command_id) == "SENT_TO_EA"


def test_ack_rejects_claim_that_expired_since_poll(client):
    user_id, command_id = _approved_command(client)
    _claim_command(client, user_id, command_id)
    past = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(minutes=1)
    _set_command(command_id, expires_at=past)
    denied = _ack(client, command_id)
    assert denied.status_code == 409
    assert _status(command_id) == "SENT_TO_EA"


@pytest.mark.parametrize("terminal_state", [
    "EXPIRED", "FAILED", "EXECUTED_OPEN", "FULLY_CLOSED",
])
def test_ack_refuses_terminal_or_stale_command_state(client, terminal_state):
    user_id, command_id = _approved_command(client)
    _claim_command(client, user_id, command_id)
    _set_command(command_id, status=terminal_state)
    denied = _ack(client, command_id)
    assert denied.status_code == 409
    assert _status(command_id) == terminal_state


def test_ack_rejects_after_no_order_execution_failure_recorded(client):
    user_id, command_id = _approved_command(client)
    _claim_command(client, user_id, command_id)
    failed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "FAILED", "error_code": "TRADING_DISABLED",
              "error_message": "Synthetic pre-broker refusal"},
        headers=EA_HEADERS,
    )
    assert failed.status_code == 200
    assert _status(command_id) == "FAILED"
    denied = _ack(client, command_id)
    assert denied.status_code == 409


def test_ack_does_not_waive_ea_authentication(client):
    user_id, command_id = _approved_command(client)
    _claim_command(client, user_id, command_id)
    assert _ack(client, command_id, headers={}).status_code == 401
    assert _ack(client, command_id).status_code == 200


def test_ack_guard_fetches_fresh_locked_command():
    """Structural companion; the PostgreSQL race test proves actual behaviour."""
    source = (
        Path(__file__).resolve().parents[1] / "app/routes/commands.py"
    ).read_text(encoding="utf-8")
    block = source.split("def command_received(", 1)[1].split(
        "def report_execution(", 1
    )[0]
    assert "with_for_update=True" in block
    assert "populate_existing=True" in block
    assert block.index("with_for_update=True") < block.index(
        'command.status != "SENT_TO_EA"'
    )


def test_ack_serializes_with_concurrent_terminal_commit_on_postgres(client):
    """An ACK cannot return 200 based on stale pre-FAILURE status.

    A separately committed writer holds a PostgreSQL FOR UPDATE row lock.
    The HTTP ACK must block until its FAILED update commits, then see 409.
    Skipped for SQLite, which cannot provide equivalent row-lock semantics.
    """
    with SessionLocal() as check:
        if check.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL transaction row locking")

    user_id, command_id = _approved_command(client)
    _claim_command(client, user_id, command_id)
    entered = Event()
    with SessionLocal() as writer:
        command = writer.get(models.Command, command_id, with_for_update=True)
        assert command is not None
        command.status = "FAILED"
        writer.flush()  # The change is invisible until this writer commits.

        def try_ack():
            entered.set()
            return _ack(client, command_id)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(try_ack)
            try:
                assert entered.wait(5), "ACK request thread did not start"
                time.sleep(0.35)
                assert not future.done(), (
                    "ACK completed while an earlier terminal transition held "
                    "the same PostgreSQL command row lock"
                )
            finally:
                # Always release the lock, including on assertion failure.
                writer.commit()
            response = future.result(timeout=15)

    assert response.status_code == 409
    assert _status(command_id) == "FAILED"
