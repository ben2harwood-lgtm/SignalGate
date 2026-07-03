"""Tests for the hosted multi-customer licensing / activation layer.

These cover license issuance, EA-user resolution by license key, customer
deactivation blocking command delivery, and REQUIRE_LICENSE (hosted) mode.
The local demo path (identify EA by user_id) must keep working when
REQUIRE_LICENSE is off — that is covered by the existing command tests.
"""
from __future__ import annotations

from app import crud
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _approve(client, signal_id, telegram_id):
    return client.post(
        f"/signals/{signal_id}/approve",
        json={"telegram_user_id": telegram_id},
    )


def test_new_user_is_issued_a_license_key(client):
    user = register_user(client, telegram_id="123")
    assert user["license_key"], "new user should receive a license key"
    assert user["license_key"].startswith("SG-")


def test_admin_can_issue_and_list_licenses(client):
    register_user(client, telegram_id="123")
    resp = client.post("/admin/users/123/issue_license", headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text
    key = resp.json()["license_key"]
    assert key.startswith("SG-")

    listing = client.get("/admin/users", headers=ADMIN_HEADERS)
    assert listing.status_code == 200
    users = listing.json()["users"]
    assert any(u["license_key"] == key for u in users)


def test_resolve_ea_user_by_license(client):
    register_user(client, telegram_id="123")
    db = SessionLocal()
    try:
        user = crud.get_user_by_telegram(db, "123")
        # valid license resolves to the user
        assert crud.resolve_ea_user(db, license_key=user.license_key).id == user.id
        # unknown license does not resolve
        assert crud.resolve_ea_user(db, license_key="SG-XXXX-XXXX-XXXX") is None
    finally:
        db.close()


def test_deactivated_customer_gets_no_command(client):
    register_user(client, telegram_id="123")
    sig = create_signal(client, VALID)
    assert _approve(client, sig["id"], "123").json()["result"] == "APPROVED"

    # Deactivate the customer, then the EA poll should return no command.
    assert client.post("/admin/users/123/deactivate", headers=ADMIN_HEADERS).status_code == 200
    poll = client.get("/commands/pending", params={"user_id": "USER-000001"}, headers=EA_HEADERS)
    assert poll.json()["command"] is None

    # Reactivating restores delivery.
    assert client.post("/admin/users/123/activate", headers=ADMIN_HEADERS).status_code == 200
    poll2 = client.get("/commands/pending", params={"user_id": "USER-000001"}, headers=EA_HEADERS)
    assert poll2.json()["command"] is not None


def test_pending_by_license_key(client):
    user = register_user(client, telegram_id="123")
    sig = create_signal(client, VALID)
    _approve(client, sig["id"], "123")
    # Poll using ONLY the license key (no user_id) — the hosted EA flow.
    poll = client.get(
        "/commands/pending",
        params={"license_key": user["license_key"]},
        headers=EA_HEADERS,
    )
    assert poll.json()["command"] is not None
    assert poll.json()["command"]["symbol"] == "XAUUSD"


def test_require_license_mode_rejects_userid_only(client):
    """In hosted mode, user_id alone must not yield commands; a valid license must."""
    user = register_user(client, telegram_id="123")
    sig = create_signal(client, VALID)
    _approve(client, sig["id"], "123")

    crud.settings.require_license = True
    try:
        # user_id only -> blocked in hosted mode
        poll = client.get(
            "/commands/pending", params={"user_id": "USER-000001"}, headers=EA_HEADERS
        )
        assert poll.json()["command"] is None
        # valid license -> delivered
        poll2 = client.get(
            "/commands/pending",
            params={"license_key": user["license_key"]},
            headers=EA_HEADERS,
        )
        assert poll2.json()["command"] is not None
    finally:
        crud.settings.require_license = False
