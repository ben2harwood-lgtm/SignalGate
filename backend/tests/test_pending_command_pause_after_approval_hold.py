"""Known HOLD: an approved command must not cross a later admin pause.

Synthetic TestClient regression only: no MT5, broker, paid provider, customer
data, or network integration. The strict XFAIL documents an existing guard gap;
do not remove it until the implementation is independently reviewed and
tested against real two-session PostgreSQL pause/claim ordering.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


class _PausedCommandDelivered(AssertionError):
    """EA received an approved command after the admin pause was committed."""


@pytest.mark.xfail(
    strict=True,
    raises=_PausedCommandDelivered,
    reason=(
        "HOLD: an approved PENDING command is still claimed by /commands/pending "
        "after the global admin pause; independent PostgreSQL proof required"
    ),
)
def test_pending_command_is_not_delivered_after_admin_pause(client):
    """A pause after YES, but before the EA poll, should deny new delivery."""
    user = register_user(client, "990001")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]

    paused = client.post("/admin/pause", headers=ADMIN_HEADERS)
    assert paused.status_code == 200

    # Confirm that the pause actually committed, not merely that the
    # endpoint returned 200. An unrelated setup failure must fail CI.
    with SessionLocal() as session:
        pause_row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert pause_row is not None and pause_row.value == "true"

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

    # Only the specific unsafe delivery should count as the known XFAIL.
    # Wrong responses, broken setup, or inconsistent audit state must fail CI.
    if payload["command"] is not None:
        assert payload["command"]["command_id"] == command_id
        assert command.status == "SENT_TO_EA"
        assert sent_audits == 1
        # An execution side effect must fail CI, not be hidden by strict XFAIL.
        assert executions == 0
        raise _PausedCommandDelivered(
            f"EA received {command_id} after the committed admin pause"
        )

    # These assertions become release criteria only after the safety fix,
    # strict-XFAIL removal, actual two-session PG tests and independent review.
    assert command.status == "PENDING"
    assert sent_audits == 0
    assert executions == 0
