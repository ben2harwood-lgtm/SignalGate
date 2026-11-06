"""Offline positive control for the admin-pause EA polling safety repair.

A future fail-closed poll-time pause guard must not strand an already-approved
PENDING command after an explicit admin resume. This proves only HTTP/DB
liveness on synthetic demo data; it is not an MT5 or broker receipt.
"""
from __future__ import annotations

from sqlalchemy import select

from app import models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def test_approved_pending_command_delivered_once_after_admin_resume(client):
    """YES -> pause -> resume -> one poll claim, with no invented execution."""
    user = register_user(client, "990004")
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
    assert paused.json()["admin_paused"] is True
    with SessionLocal() as session:
        row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        command = session.get(models.Command, command_id)
        assert row is not None and row.value == "true"
        assert command is not None and command.status == "PENDING"

    # No EA poll while paused: that separate known unsafe path is covered by
    # test_pending_command_pause_after_approval_hold.py (strict XFAIL).
    resumed = client.post("/admin/resume", headers=ADMIN_HEADERS)
    assert resumed.status_code == 200
    assert resumed.json()["admin_paused"] is False
    with SessionLocal() as session:
        row = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        command = session.get(models.Command, command_id)
        assert row is not None and row.value == "false"
        assert command is not None and command.status == "PENDING"

    params = {"user_id": user["id"]}
    first = client.get("/commands/pending", params=params, headers=EA_HEADERS)
    assert first.status_code == 200
    assert first.json()["command"] is not None
    assert first.json()["command"]["command_id"] == command_id

    second = client.get("/commands/pending", params=params, headers=EA_HEADERS)
    assert second.status_code == 200
    assert second.json()["command"] is None

    with SessionLocal() as session:
        command = session.get(models.Command, command_id)
        assert command is not None and command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert (
            session.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
            == 1
        )
        assert session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "ADMIN_PAUSE"
        ).count() == 1
        assert session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "ADMIN_RESUME"
        ).count() == 1
        assert session.query(models.Execution).count() == 0
