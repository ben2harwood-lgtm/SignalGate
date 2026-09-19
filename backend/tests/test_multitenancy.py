"""Provider multi-tenancy isolation tests."""
from __future__ import annotations

import hashlib

from app import crud, models, security
from app.database import SessionLocal

from .conftest import register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353"


def _provision(name: str, source: str, role: str = "OPERATOR"):
    db = SessionLocal()
    try:
        org = crud.create_provider_organization(db, name)
        feed = crud.create_provider_feed(db, org.id, f"{name} Feed", source)
        credential, secret = crud.issue_provider_credential(db, org.id, role=role)
        db.commit()
        return {
            "org_id": org.id,
            "feed_id": feed.id,
            "source": feed.source_namespace,
            "credential_id": credential.id,
            "secret": secret,
        }
    finally:
        db.close()


def _headers(provider: dict) -> dict:
    return {"X-Signal-Provider-API-Key": provider["secret"]}


def _set_hosted(enabled: bool) -> None:
    security.settings.require_license = enabled


def test_provider_signal_creation_is_tenant_bound(client):
    a = _provision("Provider A", "TELEGRAM_CHAT:1001")
    b = _provision("Provider B", "TELEGRAM_CHAT:2002")

    _set_hosted(True)
    try:
        own = client.post(
            "/signals/create",
            json={
                "raw_text": VALID,
                "source": a["source"],
                "source_message_id": "42",
            },
            headers=_headers(a),
        )
        assert own.status_code == 200, own.text
        assert own.json()["feed_id"] == a["feed_id"]

        cross = client.post(
            "/signals/create",
            json={
                "raw_text": VALID,
                "source": b["source"],
                "source_message_id": "42",
            },
            headers=_headers(a),
        )
        assert cross.status_code == 403

        feeds = client.get("/provider/feeds", headers=_headers(a))
        assert feeds.status_code == 200
        assert [row["id"] for row in feeds.json()] == [a["feed_id"]]

        hidden = client.get(
            f"/provider/feeds/{b['feed_id']}/signals", headers=_headers(a)
        )
        assert hidden.status_code == 404
    finally:
        _set_hosted(False)


def test_recipient_lookup_cannot_leak_other_feed_subscribers(client):
    user_a = register_user(client, "101", username="alpha")
    user_b = register_user(client, "202", username="beta")
    a = _provision("Provider A", "TELEGRAM_CHAT:1001")
    b = _provision("Provider B", "TELEGRAM_CHAT:2002")

    _set_hosted(True)
    try:
        subscribed = client.post(
            f"/provider/feeds/{a['feed_id']}/subscribers",
            json={"telegram_user_id": "101"},
            headers=_headers(a),
        )
        assert subscribed.status_code == 200, subscribed.text

        # Provider B cannot mutate Provider A even when it knows the feed id.
        cross = client.post(
            f"/provider/feeds/{a['feed_id']}/subscribers",
            json={"telegram_user_id": "202"},
            headers=_headers(b),
        )
        assert cross.status_code == 404

        signal = client.post(
            "/signals/create",
            json={
                "raw_text": VALID,
                "source": a["source"],
                "source_message_id": "77",
            },
            headers=_headers(a),
        )
        assert signal.status_code == 200, signal.text

        recipients = client.get(
            "/signals/recipients",
            params={"signal_id": signal.json()["id"]},
            headers=_headers(a),
        )
        assert recipients.status_code == 200
        assert recipients.json()["recipients"] == [
            {"user_id": user_a["id"], "telegram_user_id": "101"}
        ]

        hidden = client.get(
            "/signals/recipients",
            params={"signal_id": signal.json()["id"]},
            headers=_headers(b),
        )
        assert hidden.status_code == 404
        assert user_b["id"] not in hidden.text
    finally:
        _set_hosted(False)


def test_unsubscribed_user_cannot_create_command(client):
    register_user(client, "101", username="alpha")
    register_user(client, "202", username="beta")
    a = _provision("Provider A", "TELEGRAM_CHAT:1001")

    _set_hosted(True)
    old_registration = security.settings.registration_api_key
    security.settings.registration_api_key = "r" * 40
    try:
        assert client.post(
            f"/provider/feeds/{a['feed_id']}/subscribers",
            json={"telegram_user_id": "101"},
            headers=_headers(a),
        ).status_code == 200

        signal = client.post(
            "/signals/create",
            json={
                "raw_text": VALID,
                "source": a["source"],
                "source_message_id": "88",
            },
            headers=_headers(a),
        ).json()

        denied = client.post(
            f"/signals/{signal['id']}/approve",
            json={"telegram_user_id": "202"},
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert denied.status_code == 200
        assert denied.json()["result"] == "NOT_SUBSCRIBED"
        assert denied.json()["command_id"] is None

        allowed = client.post(
            f"/signals/{signal['id']}/approve",
            json={"telegram_user_id": "101"},
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert allowed.status_code == 200
        assert allowed.json()["result"] == "APPROVED"
        assert allowed.json()["command_id"] is not None
    finally:
        security.settings.registration_api_key = old_registration
        _set_hosted(False)


def test_provider_pause_is_tenant_scoped_and_fail_closed(client):
    a = _provision("Provider A", "TELEGRAM_CHAT:1001")
    b = _provision("Provider B", "TELEGRAM_CHAT:2002")

    _set_hosted(True)
    try:
        assert client.post(
            f"/provider/feeds/{a['feed_id']}/pause", headers=_headers(b)
        ).status_code == 404

        paused = client.post(
            f"/provider/feeds/{a['feed_id']}/pause", headers=_headers(a)
        )
        assert paused.status_code == 200
        assert paused.json()["paused"] is True

        blocked = client.post(
            "/signals/create",
            json={
                "raw_text": VALID,
                "source": a["source"],
                "source_message_id": "91",
            },
            headers=_headers(a),
        )
        assert blocked.status_code == 409

        resumed = client.post(
            f"/provider/feeds/{a['feed_id']}/resume", headers=_headers(a)
        )
        assert resumed.status_code == 200
        assert resumed.json()["paused"] is False
    finally:
        _set_hosted(False)


def test_viewer_credential_is_read_only(client):
    viewer = _provision("Read Only", "TELEGRAM_CHAT:3003", role="VIEWER")

    _set_hosted(True)
    try:
        feeds = client.get("/provider/feeds", headers=_headers(viewer))
        assert feeds.status_code == 200
        assert len(feeds.json()) == 1

        denied = client.post(
            f"/provider/feeds/{viewer['feed_id']}/pause",
            headers=_headers(viewer),
        )
        assert denied.status_code == 403
    finally:
        _set_hosted(False)


def test_provider_secret_is_not_stored_in_plaintext(client):
    provider = _provision("Provider A", "TELEGRAM_CHAT:1001")
    db = SessionLocal()
    try:
        credential = db.get(models.ProviderCredential, provider["credential_id"])
        assert credential is not None
        assert credential.key_hash != provider["secret"]
        assert credential.key_hash == hashlib.sha256(
            provider["secret"].encode("utf-8")
        ).hexdigest()
        assert provider["secret"] not in (credential.key_prefix, credential.key_hash)
    finally:
        db.close()


def test_blocked_approval_retry_does_not_claim_it_was_executed(client):
    register_user(client, "202", username="beta")
    a = _provision("Provider A", "TELEGRAM_CHAT:1001")

    _set_hosted(True)
    old_registration = security.settings.registration_api_key
    security.settings.registration_api_key = "r" * 40
    try:
        signal = client.post(
            "/signals/create",
            json={
                "raw_text": VALID,
                "source": a["source"],
                "source_message_id": "99",
            },
            headers=_headers(a),
        ).json()
        decision_headers = {"X-Registration-API-Key": "r" * 40}
        first = client.post(
            f"/signals/{signal['id']}/approve",
            json={"telegram_user_id": "202"},
            headers=decision_headers,
        )
        second = client.post(
            f"/signals/{signal['id']}/approve",
            json={"telegram_user_id": "202"},
            headers=decision_headers,
        )
        assert first.json()["result"] == "NOT_SUBSCRIBED"
        assert second.json()["result"] == "ALREADY_BLOCKED"
        assert second.json()["command_id"] is None
    finally:
        security.settings.registration_api_key = old_registration
        _set_hosted(False)
