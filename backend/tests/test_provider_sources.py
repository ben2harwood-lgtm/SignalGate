"""Tenant-bound Telegram provider source tests."""
from __future__ import annotations

import io
import os
from pathlib import Path

from app import crud, models, security

from .conftest import register_user

_FAKE_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)

EUR_BUY = "EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950"
GBPJPY_SELL = "GBPJPY SELL SL 191.00 TP1 189.00 TP2 188.00"


def _provider(db, slug: str):
    org = crud.create_organization(db, f"{slug} org", f"{slug}-org")
    provider = crud.create_provider(db, org.id, f"{slug} provider", slug)
    feed = crud.create_feed(db, provider, f"{slug} feed", f"{slug}-source")
    _credential, raw_key = crud.issue_provider_credential(db, provider)
    db.commit()
    return provider, feed, raw_key


def _headers(provider, key):
    return {"X-Provider-Id": provider.id, "X-Provider-API-Key": key}


def _source_invite(client, provider, feed, key, expires_minutes=60):
    response = client.post(
        "/providers/me/source-invites",
        json={"feed_id": feed.id, "expires_minutes": expires_minutes},
        headers=_headers(provider, key),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _connect(client, invite, telegram_user_id, headers=None):
    return client.post(
        "/provider-sources/telegram/connect",
        json={
            "connection_token": invite["connection_token"],
            "telegram_user_id": telegram_user_id,
        },
        headers=headers or {},
    )


def test_source_token_returned_once_but_never_persisted_or_listed(client, db):
    provider, feed, key = _provider(db, "source-token")
    created = _source_invite(client, provider, feed, key)
    raw = created["connection_token"]
    assert raw.startswith("sgs_")

    invite = db.get(models.ProviderSourceInvite, created["invite_id"])
    assert invite.token_hash == crud.hash_provider_source_token(raw)
    assert raw != invite.token_hash

    listing = client.get(
        "/providers/me/source-invites",
        headers=_headers(provider, key),
    )
    row = next(x for x in listing.json() if x["invite_id"] == invite.id)
    assert row["connection_token"] is None

    audit_rows = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.entity_id == invite.id)
        .all()
    )
    assert audit_rows
    assert all(raw not in (row.payload_json or "") for row in audit_rows)


def test_connect_status_and_one_use_semantics(client, db):
    provider, feed, key = _provider(db, "source-connect")
    invite = _source_invite(client, provider, feed, key)
    connected = _connect(client, invite, "9201")
    assert connected.status_code == 200, connected.text
    body = connected.json()
    assert body["provider_id"] == provider.id
    assert body["feed_id"] == feed.id
    assert body["source_type"] == "TELEGRAM"

    status = client.get(
        "/provider-sources/telegram/status",
        params={"telegram_user_id": "9201"},
    )
    assert status.status_code == 200
    assert status.json()["binding_id"] == body["binding_id"]

    replay = _connect(client, invite, "9201")
    assert replay.status_code == 400
    db.expire_all()
    assert db.query(models.ProviderSourceBinding).count() == 1


def test_rebinding_requires_a_new_provider_owned_token_and_is_audited(client, db):
    p1, f1, k1 = _provider(db, "source-a")
    p2, f2, k2 = _provider(db, "source-b")
    first = _source_invite(client, p1, f1, k1)
    second = _source_invite(client, p2, f2, k2)

    a = _connect(client, first, "9202")
    b = _connect(client, second, "9202")
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["binding_id"] == b.json()["binding_id"]
    assert b.json()["provider_id"] == p2.id
    assert b.json()["feed_id"] == f2.id

    db.expire_all()
    binding = db.get(models.ProviderSourceBinding, b.json()["binding_id"])
    assert binding.provider_id == p2.id
    audit = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "PROVIDER_SOURCE_CONNECTED",
            models.AuditLog.entity_id == binding.id,
        )
        .order_by(models.AuditLog.created_at.desc())
        .first()
    )
    assert audit is not None
    assert p1.id in (audit.payload_json or "")


def test_provider_cannot_manage_other_provider_source_objects(client, db):
    p1, f1, k1 = _provider(db, "manage-a")
    p2, f2, k2 = _provider(db, "manage-b")
    invite = _source_invite(client, p1, f1, k1)

    cross_create = client.post(
        "/providers/me/source-invites",
        json={"feed_id": f1.id, "expires_minutes": 60},
        headers=_headers(p2, k2),
    )
    assert cross_create.status_code == 404

    cross_revoke = client.post(
        f"/providers/me/source-invites/{invite['invite_id']}/revoke",
        headers=_headers(p2, k2),
    )
    assert cross_revoke.status_code == 404

    connected = _connect(client, invite, "9203").json()
    p2_bindings = client.get(
        "/providers/me/source-bindings",
        headers=_headers(p2, k2),
    )
    assert connected["binding_id"] not in {
        row["binding_id"] for row in p2_bindings.json()
    }
    cross_binding_revoke = client.post(
        f"/providers/me/source-bindings/{connected['binding_id']}/revoke",
        headers=_headers(p2, k2),
    )
    assert cross_binding_revoke.status_code == 404


def test_bound_source_signal_uses_tenant_feed_policy_and_replay_identity(client, db):
    provider, feed, key = _provider(db, "source-policy")
    crud.update_feed_policy(
        db,
        feed,
        {
            "allowed_symbols": ["EURUSD"],
            "expiry_minutes": 11,
            "default_lot_size": 0.04,
        },
    )
    db.commit()
    invite = _source_invite(client, provider, feed, key)
    binding = _connect(client, invite, "9204").json()

    valid = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9204",
            "raw_text": EUR_BUY,
            "source_message_id": "chat:101",
        },
    )
    assert valid.status_code == 200, valid.text
    signal = valid.json()
    assert signal["provider_id"] == provider.id
    assert signal["feed_id"] == feed.id
    assert signal["parser_status"] == "VALID"
    assert signal["source"] == f"TELEGRAM_BINDING:{binding['binding_id']}"

    blocked = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9204",
            "raw_text": GBPJPY_SELL,
            "source_message_id": "chat:102",
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["parser_status"] == "REJECTED"
    assert "not enabled" in (blocked.json()["parser_error"] or "").lower()

    duplicate = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9204",
            "raw_text": EUR_BUY,
            "source_message_id": "chat:101",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == signal["id"]

    conflict = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9204",
            "raw_text": "EURUSD BUY SL 1.0790 TP1 1.0910",
            "source_message_id": "chat:101",
        },
    )
    assert conflict.status_code == 409


def test_bound_source_recipients_are_only_that_feeds_consented_subscribers(client, db):
    p1, f1, k1 = _provider(db, "recipients-a")
    p2, f2, _k2 = _provider(db, "recipients-b")
    u1 = register_user(client, "9205", "feed_a", "Feed A")
    u2 = register_user(client, "9206", "feed_b", "Feed B")
    u3 = register_user(client, "not-a-chat-id", "non_numeric", "Non Numeric")

    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, u1["id"]))
    crud.subscribe_user_to_feed(db, p2, f2, db.get(models.User, u2["id"]))
    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, u3["id"]))
    db.commit()

    invite = _source_invite(client, p1, f1, k1)
    _connect(client, invite, "9207")

    response = client.get(
        "/provider-sources/telegram/recipients",
        params={"telegram_user_id": "9207"},
    )
    assert response.status_code == 200
    ids = {x["telegram_user_id"] for x in response.json()["recipients"]}
    assert ids == {"9205"}


def test_bound_source_extract_uses_feed_allowlist(client, db):
    provider, feed, key = _provider(db, "extract-policy")
    crud.update_feed_policy(db, feed, {"allowed_symbols": ["EURUSD"]})
    db.commit()
    invite = _source_invite(client, provider, feed, key)
    _connect(client, invite, "9208")

    os.environ.pop("FAKE_EXTRACTOR_TEXT", None)
    rejected = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": "9208"},
        files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert rejected.status_code == 200
    assert rejected.json()["symbol"] == "XAUUSD"
    assert rejected.json()["parser_status"] == "REJECTED"
    assert "not enabled" in (rejected.json()["parser_error"] or "").lower()

    crud.update_feed_policy(db, feed, {"allowed_symbols": ["XAUUSD"]})
    db.commit()
    accepted = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": "9208"},
        files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert accepted.status_code == 200
    assert accepted.json()["parser_status"] == "VALID"


def test_unbound_or_revoked_source_cannot_extract_create_or_broadcast(client, db):
    for path, kwargs in (
        (
            "/provider-sources/telegram/signals",
            {
                "json": {
                    "telegram_user_id": "9209",
                    "raw_text": EUR_BUY,
                    "source_message_id": "1",
                }
            },
        ),
        (
            "/provider-sources/telegram/recipients",
            {"params": {"telegram_user_id": "9209"}},
        ),
    ):
        response = (
            client.post(path, **kwargs)
            if "json" in kwargs
            else client.get(path, **kwargs)
        )
        assert response.status_code == 403

    provider, feed, key = _provider(db, "revoke-source")
    invite = _source_invite(client, provider, feed, key)
    connected = _connect(client, invite, "9210").json()
    revoked = client.post(
        f"/providers/me/source-bindings/{connected['binding_id']}/revoke",
        headers=_headers(provider, key),
    )
    assert revoked.status_code == 200

    status = client.get(
        "/provider-sources/telegram/status",
        params={"telegram_user_id": "9210"},
    )
    assert status.status_code == 404
    denied = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9210",
            "raw_text": EUR_BUY,
            "source_message_id": "1",
        },
    )
    assert denied.status_code == 403


def test_hosted_source_calls_require_bot_registration_secret(client, db):
    provider, feed, key = _provider(db, "hosted-source")
    invite = _source_invite(client, provider, feed, key)

    old_require = security.settings.require_license
    old_registration = security.settings.registration_api_key
    security.settings.require_license = True
    security.settings.registration_api_key = "r" * 40
    try:
        denied = _connect(client, invite, "9211")
        assert denied.status_code == 401
        allowed = _connect(
            client,
            invite,
            "9211",
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert allowed.status_code == 200, allowed.text

        no_secret = client.post(
            "/provider-sources/telegram/signals",
            json={
                "telegram_user_id": "9211",
                "raw_text": EUR_BUY,
                "source_message_id": "1",
            },
        )
        assert no_secret.status_code == 401
        with_secret = client.post(
            "/provider-sources/telegram/signals",
            json={
                "telegram_user_id": "9211",
                "raw_text": EUR_BUY,
                "source_message_id": "1",
            },
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert with_secret.status_code == 200
    finally:
        security.settings.registration_api_key = old_registration
        security.settings.require_license = old_require


def test_portal_and_bot_are_wired_to_tenant_source_routes(client):
    portal = client.get("/provider-portal")
    assert portal.status_code == 200
    assert "/providers/me/source-invites" in portal.text
    assert "/providers/me/source-bindings" in portal.text
    assert "/connectprovider " in portal.text

    root = Path(__file__).resolve().parents[2]
    bot_source = (root / "telegram_bot" / "bot.py").read_text(encoding="utf-8")
    handler_source = (root / "telegram_bot" / "handlers.py").read_text(encoding="utf-8")
    assert 'CommandHandler("connectprovider", handlers.connect_provider_source)' in bot_source
    assert '"/provider-sources/telegram/signals"' in handler_source
    assert '"/provider-sources/telegram/extract"' in handler_source
    assert '"/provider-sources/telegram/recipients"' in handler_source
