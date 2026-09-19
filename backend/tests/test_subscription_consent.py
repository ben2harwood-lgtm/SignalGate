"""Subscriber-consent and provider invite isolation tests."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from app import crud, models, security
from app.database import SessionLocal

from .conftest import register_user


def _provider(db, slug: str):
    org = crud.create_organization(db, f"{slug} org", f"{slug}-org")
    provider = crud.create_provider(db, org.id, f"{slug} provider", slug)
    feed = crud.create_feed(db, provider, f"{slug} feed", f"{slug}-source")
    _credential, raw_key = crud.issue_provider_credential(db, provider)
    db.commit()
    return provider, feed, raw_key


def _headers(provider, key):
    return {"X-Provider-Id": provider.id, "X-Provider-API-Key": key}


def _create_invite(client, provider, feed, key, expires_minutes=1440):
    response = client.post(
        "/providers/me/subscription-invites",
        json={"feed_id": feed.id, "expires_minutes": expires_minutes},
        headers=_headers(provider, key),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_direct_provider_enrolment_is_disabled(client, db):
    provider, feed, key = _provider(db, "direct-disabled")
    register_user(client, "9101", "target", "Target")

    response = client.post(
        "/providers/me/subscriptions",
        json={"feed_id": feed.id, "telegram_user_id": "9101"},
        headers=_headers(provider, key),
    )
    assert response.status_code == 410

    db.expire_all()
    assert db.query(models.Subscription).count() == 0
    assert db.query(models.TradingAccount).count() == 0


def test_invite_raw_token_is_returned_once_but_not_persisted_or_audited(client, db):
    provider, feed, key = _provider(db, "token-storage")
    created = _create_invite(client, provider, feed, key)
    raw = created["invite_token"]

    assert raw.startswith("sgi_")
    invite = db.get(models.SubscriptionInvite, created["invite_id"])
    assert invite.token_hash == crud.hash_subscription_invite_token(raw)
    assert raw != invite.token_hash

    listing = client.get(
        "/providers/me/subscription-invites",
        headers=_headers(provider, key),
    )
    assert listing.status_code == 200
    row = next(x for x in listing.json() if x["invite_id"] == invite.id)
    assert row["invite_token"] is None

    audit_rows = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.entity_id == invite.id)
        .all()
    )
    assert audit_rows
    assert all(raw not in (row.payload_json or "") for row in audit_rows)


def test_subscriber_acceptance_creates_subscription_and_account(client, db):
    provider, feed, key = _provider(db, "consent")
    user = register_user(client, "9102", "consenting", "Consenting")
    invite = _create_invite(client, provider, feed, key)

    before = client.get(
        "/providers/me/subscribers",
        params={"feed_id": feed.id},
        headers=_headers(provider, key),
    )
    assert before.status_code == 200
    assert before.json()["subscribers"] == []

    accepted = client.post(
        "/subscriptions/accept",
        json={
            "invite_token": invite["invite_token"],
            "telegram_user_id": user["telegram_user_id"],
        },
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["provider_id"] == provider.id
    assert body["feed_id"] == feed.id
    assert body["status"] == "ACTIVE"

    after = client.get(
        "/providers/me/subscribers",
        params={"feed_id": feed.id},
        headers=_headers(provider, key),
    )
    ids = {x["telegram_user_id"] for x in after.json()["subscribers"]}
    assert user["telegram_user_id"] in ids

    db.expire_all()
    assert db.query(models.Subscription).count() == 1
    assert db.query(models.TradingAccount).count() == 1
    stored = db.get(models.SubscriptionInvite, invite["invite_id"])
    assert stored.status == "ACCEPTED"
    assert stored.accepted_user_id == user["id"]
    assert stored.accepted_at is not None


def test_invite_cannot_be_replayed_by_same_or_different_subscriber(client, db):
    provider, feed, key = _provider(db, "one-use")
    first = register_user(client, "9103", "first", "First")
    second = register_user(client, "9104", "second", "Second")
    invite = _create_invite(client, provider, feed, key)
    payload = {
        "invite_token": invite["invite_token"],
        "telegram_user_id": first["telegram_user_id"],
    }
    assert client.post("/subscriptions/accept", json=payload).status_code == 200

    replay = client.post("/subscriptions/accept", json=payload)
    theft = client.post(
        "/subscriptions/accept",
        json={
            "invite_token": invite["invite_token"],
            "telegram_user_id": second["telegram_user_id"],
        },
    )
    assert replay.status_code == 400
    assert theft.status_code == 400

    db.expire_all()
    assert db.query(models.Subscription).count() == 1
    assert db.query(models.TradingAccount).count() == 1


def test_expired_and_revoked_invites_fail_closed(client, db):
    provider, feed, key = _provider(db, "expiry")
    user = register_user(client, "9105", "expiry_user", "Expiry")

    expired = _create_invite(client, provider, feed, key)
    row = db.get(models.SubscriptionInvite, expired["invite_id"])
    row.expires_at = models.utcnow() - dt.timedelta(seconds=1)
    db.commit()

    response = client.post(
        "/subscriptions/accept",
        json={
            "invite_token": expired["invite_token"],
            "telegram_user_id": user["telegram_user_id"],
        },
    )
    assert response.status_code == 410
    db.expire_all()
    assert db.get(models.SubscriptionInvite, expired["invite_id"]).status == "EXPIRED"

    revoked = _create_invite(client, provider, feed, key)
    revoke = client.post(
        f"/providers/me/subscription-invites/{revoked['invite_id']}/revoke",
        headers=_headers(provider, key),
    )
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "REVOKED"

    denied = client.post(
        "/subscriptions/accept",
        json={
            "invite_token": revoked["invite_token"],
            "telegram_user_id": user["telegram_user_id"],
        },
    )
    assert denied.status_code == 400


def test_provider_cannot_issue_list_or_revoke_other_provider_invites(client, db):
    p1, f1, k1 = _provider(db, "invite-a")
    p2, f2, k2 = _provider(db, "invite-b")

    cross_create = client.post(
        "/providers/me/subscription-invites",
        json={"feed_id": f1.id, "expires_minutes": 60},
        headers=_headers(p2, k2),
    )
    assert cross_create.status_code == 404

    invite = _create_invite(client, p1, f1, k1)
    p2_list = client.get(
        "/providers/me/subscription-invites",
        headers=_headers(p2, k2),
    )
    assert p2_list.status_code == 200
    assert invite["invite_id"] not in {x["invite_id"] for x in p2_list.json()}

    cross_revoke = client.post(
        f"/providers/me/subscription-invites/{invite['invite_id']}/revoke",
        headers=_headers(p2, k2),
    )
    assert cross_revoke.status_code == 404


def test_hosted_invite_acceptance_requires_bot_registration_secret(client, db):
    provider, feed, key = _provider(db, "hosted-consent")
    user = register_user(client, "9106", "hosted_user", "Hosted")
    invite = _create_invite(client, provider, feed, key)

    old_require = security.settings.require_license
    old_registration = security.settings.registration_api_key
    security.settings.require_license = True
    security.settings.registration_api_key = "r" * 40
    try:
        denied = client.post(
            "/subscriptions/accept",
            json={
                "invite_token": invite["invite_token"],
                "telegram_user_id": user["telegram_user_id"],
            },
        )
        assert denied.status_code == 401

        allowed = client.post(
            "/subscriptions/accept",
            json={
                "invite_token": invite["invite_token"],
                "telegram_user_id": user["telegram_user_id"],
            },
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert allowed.status_code == 200, allowed.text
    finally:
        security.settings.registration_api_key = old_registration
        security.settings.require_license = old_require


def test_portal_and_bot_use_consent_flow_not_direct_enrolment(client):
    portal = client.get("/provider-portal")
    assert portal.status_code == 200
    assert "/providers/me/subscription-invites" in portal.text
    assert 'api("/providers/me/subscriptions"' not in portal.text

    root = Path(__file__).resolve().parents[2]
    bot_source = (root / "telegram_bot" / "bot.py").read_text(encoding="utf-8")
    handler_source = (root / "telegram_bot" / "handlers.py").read_text(encoding="utf-8")
    assert 'CommandHandler("join", handlers.join_feed)' in bot_source
    assert '"/subscriptions/accept"' in handler_source
    assert "invite_token" in handler_source
