"""HOLD: EA command polling must fail closed on absent or corrupt global pause state.

Fabricated loopback TestClient data only. No MT5, broker, Telegram, external
service, credential, customer, or trading connection. The missing/malformed poll guard now runs normally; startup seeding and
operator-status defects remain strict XFAIL release holds.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


class _UntrustedPauseStateDelivered(AssertionError):
    """A command was delivered without an explicitly healthy unpaused row."""


@pytest.mark.parametrize("broken_setting", ("missing", "invalid-value"))
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


class _StartupReopenedUntrustedPause(AssertionError):
    """A missing persisted pause row was silently re-created as unpaused."""


@pytest.mark.xfail(
    strict=True,
    raises=_StartupReopenedUntrustedPause,
    reason=(
        "RELEASE HOLD: startup settings seeding may not silently authorize "
        "already-approved EA commands when a persisted admin pause row is missing"
    ),
)
def test_missing_pause_row_not_reseeded_after_command_approval(client):
    """Synthetic restart-seeder regression; no process, broker, or EA is started.

    First-install defaults are a separate case. Here an existing approved
    PENDING command makes this an established database, so absence of the
    pause setting is untrusted state, not consent to resume command delivery.
    Invoke the actual startup seeder directly to isolate the policy gap.
    """
    from app.main import seed_settings

    user = register_user(client, "990005")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]

    with SessionLocal() as session:
        row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert row is not None and row.value == "false"
        session.delete(row)
        session.commit()

    with SessionLocal() as session:
        assert session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        ) is None
        pending = session.get(models.Command, command_id)
        assert pending is not None and pending.status == "PENDING"

    # Exact helper run by the app lifespan on startup. This deliberately
    # exposes missing-row auto-recovery without changing production state.
    seed_settings()
    with SessionLocal() as session:
        reseeded = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        pause_value = reseeded.value if reseeded is not None else None

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

    # The named XFAIL is allowed ONLY after proving an existing database
    # was reopened permissively and delivery/audit actually occurred.
    if pause_value == "false" and payload["command"] is not None:
        assert payload["command"]["command_id"] == command_id
        assert command.status == "SENT_TO_EA"
        assert sent_audits == 1
        assert executions == 0
        raise _StartupReopenedUntrustedPause(
            "Startup seeded missing admin_paused=false and delivered a "
            "previously approved pending command without explicit resume"
        )

    # A poll-only guard is insufficient if startup still silently seeds
    # untrusted persisted state to 'false'. Require both to be safe.
    assert pause_value != "false"
    assert payload["command"] is None
    assert command.status == "PENDING"
    assert sent_audits == 0
    assert executions == 0


class _EstablishedDatabaseSilentlyUnpaused(AssertionError):
    """An existing database lost pause state and was silently reopened."""


@pytest.mark.xfail(
    strict=True,
    raises=_EstablishedDatabaseSilentlyUnpaused,
    reason=(
        "RELEASE HOLD: a database with persisted users must not recreate a "
        "missing admin_paused=false merely because it has no pending commands"
    ),
)
def test_established_database_without_commands_does_not_reseed_missing_pause(client):
    """No command-based heuristic may classify an existing database as new.

    A persisted user proves this database was previously initialized. This
    invokes the startup helper only, not a process restart or any MT5 activity.
    """
    from app.main import seed_settings

    user = register_user(client, "990006")
    with SessionLocal() as session:
        row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert row is not None and row.value == "false"
        assert session.get(models.User, user["id"]) is not None
        assert session.query(models.Command).count() == 0
        session.delete(row)
        session.commit()

    with SessionLocal() as session:
        assert session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        ) is None
        assert session.get(models.User, user["id"]) is not None

    seed_settings()

    with SessionLocal() as session:
        row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        value = row.value if row is not None else None
        assert session.get(models.User, user["id"]) is not None
        assert session.query(models.Command).count() == 0
        assert session.query(models.Execution).count() == 0
        assert session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA"
        ).count() == 0

    if value == "false":
        raise _EstablishedDatabaseSilentlyUnpaused(
            "Existing user persisted, zero commands, but startup silently "
            "recreated admin_paused=false without authenticated resume"
        )
    # A future owner-reviewed policy may leave it missing or initialize a
    # trusted paused state. A deliberate startup refusal needs its own test.
    assert value is None or value == "true"


class _OperatorReportedUntrustedPauseAsClear(AssertionError):
    """Operational status falsely represented untrusted pause state as clear."""


@pytest.mark.parametrize("broken_setting", ("missing", "invalid-value"))
@pytest.mark.xfail(
    strict=True,
    raises=_OperatorReportedUntrustedPauseAsClear,
    reason=(
        "RELEASE HOLD: admin status and metrics must not report an absent or "
        "malformed persisted pause setting as authoritatively unpaused"
    ),
)
def test_admin_status_and_metrics_fail_closed_on_untrusted_pause(client, broken_setting):
    """Offline operator-status regression, without commands or broker activity.

    A misleading green/unpaused dashboard can conceal the same corrupted
    setting that currently allows unsafe EA polling. This is an independently
    observable operator contract, not a real monitoring or deployment test.
    """
    with SessionLocal() as session:
        row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert row is not None and row.value == "false"
        assert session.query(models.Command).count() == 0
        if broken_setting == "missing":
            session.delete(row)
        else:
            row.value = "not-a-boolean"
        session.commit()

    status = client.get("/admin/status", headers=ADMIN_HEADERS)
    metrics = client.get("/admin/metrics", headers=ADMIN_HEADERS)
    assert status.status_code == 200
    assert metrics.status_code == 200
    status_body = status.json()
    metrics_body = metrics.json()
    assert status_body["settings"].get("admin_paused") == (
        None if broken_setting == "missing" else "not-a-boolean"
    )
    assert isinstance(status_body["admin_paused"], bool)
    assert isinstance(metrics_body["mode"]["admin_paused"], bool)

    with SessionLocal() as session:
        assert session.query(models.Command).count() == 0
        assert session.query(models.Execution).count() == 0
        assert session.query(models.AuditLog).count() == 0

    misleading = [
        name
        for name, value in (
            ("admin/status", status_body["admin_paused"]),
            ("admin/metrics", metrics_body["mode"]["admin_paused"]),
        )
        if value is False
    ]
    if misleading:
        raise _OperatorReportedUntrustedPauseAsClear(
            f"admin_paused={broken_setting} was reported as unpaused by "
            + ", ".join(misleading)
        )

    # With a reviewed fix this becomes the ordinary passing safety contract;
    # remove strict XFAIL only after both operator endpoints and EA polling
    # reject/reflect untrusted persisted pause state.
    assert status_body["admin_paused"] is True
    assert metrics_body["mode"]["admin_paused"] is True
