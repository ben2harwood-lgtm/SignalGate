"""HOLD: EA command polling must fail closed on absent or corrupt global pause state.

Fabricated loopback TestClient data only. No MT5, broker, Telegram, external
service, credential, customer, or trading connection. Strict XFAIL marks a
known delivery defect; it is not an accepted gate or a passing safety test.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import models
from app.database import SessionLocal

from .conftest import EA_HEADERS, create_signal, register_user


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


class _UntrustedPauseStateDelivered(AssertionError):
    """A command was delivered without an explicitly healthy unpaused row."""


@pytest.mark.parametrize("broken_setting", ("missing", "invalid-value"))
@pytest.mark.xfail(
    strict=True,
    raises=_UntrustedPauseStateDelivered,
    reason=(
        "RELEASE HOLD: a missing/malformed global pause setting must not "
        "authorize delivery of a previously approved EA command"
    ),
)
def test_pending_command_denied_on_untrusted_admin_pause_setting(
    client, broken_setting
):
    """Poll after approval; only then corrupt the global pause evidence."""
    user = register_user(client, "990003")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]

    # Make the failure mode a missing row or an unrecognized value, not an
    # ordinary admin pause. Do this after the app lifespan has seeded values.
    with SessionLocal() as session:
        pause_row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert pause_row is not None and pause_row.value == "false"
        if broken_setting == "missing":
            session.delete(pause_row)
        else:
            pause_row.value = "not-a-boolean"
        session.commit()

    polled = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    )
    assert polled.status_code == 200
    payload = polled.json()
    assert "command" in payload

    with SessionLocal() as session:
        command = session.get(models.Command, command_id)
        assert command is not None
        sent_audits = (
            session.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
        )
        executions = session.query(models.Execution).count()

    # Raise only the named, expected failure on the current unsafe delivery.
    # Any setup error or unrelated assertion must be a genuine CI failure.
    if payload["command"] is not None:
        assert payload["command"]["command_id"] == command_id
        assert command.status == "SENT_TO_EA"
        assert sent_audits == 1
        assert executions == 0
        raise _UntrustedPauseStateDelivered(
            f"EA received {command_id} with admin_paused={broken_setting}"
        )

    # These negative checks become executable pass criteria only after a
    # reviewed fail-closed implementation removes the strict XFAIL.
    assert command.status == "PENDING"
    assert sent_audits == 0
    assert executions == 0
