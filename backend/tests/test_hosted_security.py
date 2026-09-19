"""Adversarial tests for hosted authentication and fail-closed startup."""
from __future__ import annotations

import pytest

from app import security
from app.config import Settings

from .conftest import ADMIN_HEADERS, PROVIDER_HEADERS


def _set_hosted_security(enabled: bool = True):
    security.settings.require_license = enabled


def test_hosted_registration_requires_server_secret(client):
    _set_hosted_security(True)
    old = security.settings.registration_api_key
    security.settings.registration_api_key = "r" * 40
    try:
        payload = {"telegram_user_id": "321"}
        denied = client.post("/register_user", json=payload)
        assert denied.status_code == 401

        allowed = client.post(
            "/register_user",
            json=payload,
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert allowed.status_code == 200
    finally:
        security.settings.registration_api_key = old
        _set_hosted_security(False)


def test_hosted_admin_id_alone_is_not_a_credential(client):
    _set_hosted_security(True)
    old = security.settings.admin_api_key
    security.settings.admin_api_key = "a" * 40
    try:
        denied = client.get("/admin/status", headers=ADMIN_HEADERS)
        assert denied.status_code == 403

        headers = {**ADMIN_HEADERS, "X-Admin-API-Key": "a" * 40}
        allowed = client.get("/admin/status", headers=headers)
        assert allowed.status_code == 200
    finally:
        security.settings.admin_api_key = old
        _set_hosted_security(False)


def test_hosted_provider_requires_tenant_scoped_provider_secret(client):
    from app import crud
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        org = crud.create_provider_organization(db, "Provider A")
        feed = crud.create_provider_feed(
            db, org.id, "Gold", "TELEGRAM_CHAT:777"
        )
        _credential, secret = crud.issue_provider_credential(db, org.id)
        db.commit()
    finally:
        db.close()

    _set_hosted_security(True)
    try:
        denied = client.post(
            "/signals/create",
            json={
                "raw_text": "XAUUSD BUY SL 2343 TP1 2353",
                "source": feed.source_namespace,
                "source_message_id": "1",
            },
            headers=PROVIDER_HEADERS,
        )
        assert denied.status_code == 403

        # The old shared provider secret is deliberately not a hosted credential.
        shared = {
            **PROVIDER_HEADERS,
            "X-Signal-Provider-API-Key": "p" * 40,
        }
        assert client.post(
            "/signals/create",
            json={
                "raw_text": "XAUUSD BUY SL 2343 TP1 2353",
                "source": feed.source_namespace,
                "source_message_id": "2",
            },
            headers=shared,
        ).status_code == 403

        headers = {"X-Signal-Provider-API-Key": secret}
        allowed = client.post(
            "/signals/create",
            json={
                "raw_text": "XAUUSD BUY SL 2343 TP1 2353",
                "source": feed.source_namespace,
                "source_message_id": "3",
            },
            headers=headers,
        )
        assert allowed.status_code == 200
        assert allowed.json()["feed_id"] == feed.id
    finally:
        _set_hosted_security(False)


def test_startup_refuses_live_mode(monkeypatch):
    monkeypatch.setenv("DEMO_ONLY_MODE", "false")
    monkeypatch.setenv("REQUIRE_LICENSE", "false")
    with pytest.raises(RuntimeError, match="DEMO ONLY"):
        Settings().validate_startup()


def test_hosted_startup_refuses_sqlite(monkeypatch):
    monkeypatch.setenv("DEMO_ONLY_MODE", "true")
    monkeypatch.setenv("REQUIRE_LICENSE", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unsafe.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Settings().validate_startup()


def test_hosted_startup_refuses_weak_secrets(monkeypatch):
    monkeypatch.setenv("DEMO_ONLY_MODE", "true")
    monkeypatch.setenv("REQUIRE_LICENSE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/signalgate")
    monkeypatch.setenv("BACKEND_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("EA_API_KEY", "short")
    monkeypatch.setenv("ADMIN_API_KEY", "a" * 40)
    monkeypatch.setenv("SIGNAL_PROVIDER_API_KEY", "p" * 40)
    monkeypatch.setenv("REGISTRATION_API_KEY", "r" * 40)
    with pytest.raises(RuntimeError, match="EA_API_KEY"):
        Settings().validate_startup()


def test_hosted_decision_endpoint_rejects_spoofed_telegram_id(client):
    from .conftest import create_signal, register_user

    user = register_user(client, "321")
    sig = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353")

    _set_hosted_security(True)
    old = security.settings.registration_api_key
    security.settings.registration_api_key = "r" * 40
    try:
        denied = client.post(
            f"/signals/{sig['id']}/approve",
            json={"telegram_user_id": "321"},
        )
        assert denied.status_code == 401

        allowed = client.post(
            f"/signals/{sig['id']}/approve",
            json={"telegram_user_id": "321"},
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert allowed.status_code == 200
        assert allowed.json()["result"] == "APPROVED"
    finally:
        security.settings.registration_api_key = old
        _set_hosted_security(False)
