"""Tamper-evident audit chain tests."""
from __future__ import annotations

from app import crud, models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358"


def _make_audit_history(client):
    user = register_user(client, "9301", "audit_user", "Audit")
    sig = create_signal(client, VALID)
    client.post(
        f"/signals/{sig['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    return sig


def test_audit_rows_are_hash_chained_and_admin_verification_passes(client):
    _make_audit_history(client)

    response = client.get("/admin/audit/verify", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is True
    assert result["count"] > 0
    assert result["head_hash"]

    db = SessionLocal()
    try:
        rows = (
            db.query(models.AuditLog)
            .order_by(models.AuditLog.created_at.asc(), models.AuditLog.id.asc())
            .all()
        )
        assert all(row.record_hash and len(row.record_hash) == 64 for row in rows)
        assert rows[0].prev_hash is None
        for previous, current in zip(rows, rows[1:]):
            assert current.prev_hash == previous.record_hash
    finally:
        db.close()


def test_audit_payload_tampering_is_detected(client):
    _make_audit_history(client)
    db = SessionLocal()
    try:
        row = db.query(models.AuditLog).order_by(models.AuditLog.created_at.asc()).first()
        row.payload_json = '{"tampered":true}'
        db.commit()
    finally:
        db.close()

    result = client.get("/admin/audit/verify", headers=ADMIN_HEADERS).json()
    assert result["valid"] is False
    assert result["broken_id"]


def test_audit_row_deletion_is_detected(client):
    _make_audit_history(client)
    db = SessionLocal()
    try:
        rows = (
            db.query(models.AuditLog)
            .order_by(models.AuditLog.created_at.asc(), models.AuditLog.id.asc())
            .all()
        )
        assert len(rows) >= 2
        db.delete(rows[0])
        db.commit()
    finally:
        db.close()

    result = client.get("/admin/audit/verify", headers=ADMIN_HEADERS).json()
    assert result["valid"] is False


def test_audit_timestamp_tampering_is_detected(client):
    import datetime as dt

    _make_audit_history(client)
    db = SessionLocal()
    try:
        row = db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc()).first()
        row.created_at = row.created_at + dt.timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    result = client.get("/admin/audit/verify", headers=ADMIN_HEADERS).json()
    assert result["valid"] is False


def test_audit_verify_requires_admin(client):
    assert client.get("/admin/audit/verify").status_code == 403


def test_direct_crud_verifier_matches_admin_receipt(client):
    _make_audit_history(client)
    db = SessionLocal()
    try:
        direct = crud.verify_audit_chain(db)
    finally:
        db.close()
    api = client.get("/admin/audit/verify", headers=ADMIN_HEADERS).json()
    assert direct == api
