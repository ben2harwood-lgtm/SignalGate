"""Offline regression: no caching of one-time credentials and provider exports."""
from __future__ import annotations

from app import crud

from .conftest import ADMIN_HEADERS


def _must_not_cache(response, secret_field: str) -> None:
    assert response.status_code == 200, response.text
    assert response.json()[secret_field]
    assert response.headers.get("cache-control") == "no-store"


def test_customer_registration_and_explicit_rotation_are_not_cacheable(client):
    registered = client.post(
        "/register_user", json={"telegram_user_id": "85101", "telegram_username": "demo-only"}
    )
    _must_not_cache(registered, "license_key")
    first = registered.json()["license_key"]

    rotated = client.post("/admin/users/85101/issue_license", headers=ADMIN_HEADERS)
    _must_not_cache(rotated, "license_key")
    assert rotated.json()["license_key"] != first


def test_admin_demo_tenant_secret_response_is_not_cacheable(client):
    response = client.post("/admin/demo-tenant", headers=ADMIN_HEADERS)
    _must_not_cache(response, "provider_api_key")
    assert response.json()["license_key"]


def test_provider_issuance_rotation_and_invite_are_not_cacheable(client, db):
    org = crud.create_organization(db, "cache-proof org", "cache-proof-org")
    provider = crud.create_provider(db, org.id, "cache-proof provider", "cache-proof")
    feed = crud.create_feed(db, provider, "cache-proof feed", "cache-proof-source")
    db.commit()

    issued = client.post(
        f"/admin/providers/{provider.id}/credentials",
        json={"label": "offline-test"},
        headers=ADMIN_HEADERS,
    )
    _must_not_cache(issued, "api_key")
    headers = {"X-Provider-Id": provider.id, "X-Provider-API-Key": issued.json()["api_key"]}

    exported = client.get("/providers/me/export", headers=headers)
    assert exported.status_code == 200, exported.text
    assert exported.headers.get("cache-control") == "no-store"
    assert exported.json()["provider"]["id"] == provider.id

    invite = client.post(
        "/providers/me/subscription-invites",
        json={"feed_id": feed.id, "expires_minutes": 30},
        headers=headers,
    )
    _must_not_cache(invite, "invite_token")

    rotated = client.post("/providers/me/credentials/rotate", headers=headers)
    _must_not_cache(rotated, "api_key")
    assert rotated.json()["api_key"] != issued.json()["api_key"]
