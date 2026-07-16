"""Red-team tests for the hosting-hardening controls.

Each test attacks one control the way a stranger on the public internet would,
and asserts the server refuses. They build fresh app instances with hosted-mode
env so the production credentials are actually required, without disturbing the
local-demo defaults the rest of the suite relies on.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.config as config_module
from app.main import create_app

ADMIN_TOKEN = "admin-token-abcdefghijklmnopqrstuvwx"
BOT_SECRET = "bot-secret-abcdefghijklmnopqrstuvwx"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """The auth dependencies read get_settings() live, so clearing the cache
    before and after each test makes hosted env apply, then restores the
    suite's local-demo config for other test files."""
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def _hosted_client(monkeypatch, **overrides):
    """A TestClient whose app is freshly built with hosted-mode settings.

    Dependencies + middleware read get_settings() live, so setting env +
    clearing the cache + create_app() yields a fully hosted app with no reload.
    """
    env = {
        "REQUIRE_LICENSE": "true",
        "ADMIN_API_TOKEN": ADMIN_TOKEN,
        "BOT_BACKEND_SECRET": BOT_SECRET,
        "EA_API_KEY": "hosted-ea-key-not-the-default-value",
        "EXPOSE_DOCS": "false",
        "RATE_LIMIT_PER_MINUTE": "0",
    }
    env.update(overrides)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config_module.get_settings.cache_clear()
    return TestClient(create_app())


# --- Admin auth: spoofable Telegram id must NOT grant admin in hosted mode ---

def test_admin_id_header_is_rejected_when_token_configured(monkeypatch):
    client = _hosted_client(monkeypatch)
    # Attacker knows the admin's Telegram id (public) and tries the old header.
    r = client.get("/admin/ledger", headers={"X-Admin-Id": "999"})
    assert r.status_code == 401


def test_admin_token_grants_access(monkeypatch):
    client = _hosted_client(monkeypatch)
    r = client.get("/admin/ledger", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert r.status_code == 200


def test_wrong_admin_token_rejected(monkeypatch):
    client = _hosted_client(monkeypatch)
    r = client.get("/admin/ledger", headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401


# --- Bot surface: approve / register / user-lookup require the bot secret ----

def test_approve_requires_bot_secret_in_hosted_mode(monkeypatch):
    client = _hosted_client(monkeypatch)
    r = client.post("/signals/SIG-000001/approve", json={"telegram_user_id": "123"})
    assert r.status_code == 401


def test_register_requires_bot_secret_in_hosted_mode(monkeypatch):
    client = _hosted_client(monkeypatch)
    r = client.post("/register_user", json={"telegram_user_id": "123"})
    assert r.status_code == 401


def test_license_key_not_harvestable_without_bot_secret(monkeypatch):
    """The user-lookup endpoint returns a license key — the hosted credential.
    A stranger enumerating Telegram ids must not be able to read it."""
    client = _hosted_client(monkeypatch)
    r = client.get("/users/123")  # no bot secret
    assert r.status_code == 401


def test_bot_secret_allows_the_bot_through(monkeypatch):
    client = _hosted_client(monkeypatch)
    hdr = {"X-Bot-Secret": BOT_SECRET}
    r = client.post("/register_user", json={"telegram_user_id": "123"}, headers=hdr)
    assert r.status_code == 200


# --- Fail-closed boot: hosted mode must refuse local-demo defaults -----------

def test_hosted_mode_refuses_to_boot_without_secrets(monkeypatch):
    monkeypatch.setenv("REQUIRE_LICENSE", "true")
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    monkeypatch.delenv("BOT_BACKEND_SECRET", raising=False)
    monkeypatch.setenv("EA_API_KEY", "local-demo-ea-key")
    config_module.get_settings.cache_clear()
    settings = config_module.Settings()
    errors = settings.hosted_config_errors()
    assert any("ADMIN_API_TOKEN" in e for e in errors)
    assert any("BOT_BACKEND_SECRET" in e for e in errors)
    assert any("EA_API_KEY" in e for e in errors)


def test_local_mode_has_no_hosted_errors(monkeypatch):
    monkeypatch.setenv("REQUIRE_LICENSE", "false")
    config_module.get_settings.cache_clear()
    settings = config_module.Settings()
    assert settings.hosted_config_errors() == []


# --- Docs surface hidden on a public server ---------------------------------

def test_docs_hidden_in_hosted_mode(monkeypatch):
    client = _hosted_client(monkeypatch)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# --- Rate limiting on public endpoints --------------------------------------

def test_rate_limit_blocks_flood(monkeypatch):
    client = _hosted_client(monkeypatch, RATE_LIMIT_PER_MINUTE="5")
    hdr = {"X-Bot-Secret": BOT_SECRET}
    codes = [
        client.post("/register_user", json={"telegram_user_id": str(i)}, headers=hdr).status_code
        for i in range(12)
    ]
    assert 429 in codes, f"expected a 429 in {codes}"

