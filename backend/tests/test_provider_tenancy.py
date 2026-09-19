"""Adversarial Provider Edition tenancy tests."""
from __future__ import annotations

from app import crud, models, security

from .conftest import register_user

VALID = "XAUUSD BUY SL 2343 TP1 2353"


def _provider_fixture(db, slug: str):
    org = crud.create_organization(db, f"{slug} org", f"{slug}-org")
    provider = crud.create_provider(db, org.id, f"{slug} provider", slug)
    feed = crud.create_feed(db, provider, f"{slug} feed", f"{slug}-source")
    _credential, raw_key = crud.issue_provider_credential(db, provider)
    db.commit()
    return provider, feed, raw_key


def _headers(provider, raw_key):
    return {"X-Provider-Id": provider.id, "X-Provider-API-Key": raw_key}


def test_provider_cannot_read_or_broadcast_other_provider_data(client, db):
    p1, f1, k1 = _provider_fixture(db, "alpha")
    p2, f2, k2 = _provider_fixture(db, "beta")
    u1 = register_user(client, "101", "alpha_user", "Alpha")
    u2 = register_user(client, "202", "beta_user", "Beta")
    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, u1["id"]))
    crud.subscribe_user_to_feed(db, p2, f2, db.get(models.User, u2["id"]))
    db.commit()

    security.settings.require_license = True
    try:
        created = client.post(
            "/signals/create",
            json={"raw_text": VALID, "feed_id": f1.id, "source_message_id": "42"},
            headers=_headers(p1, k1),
        )
        assert created.status_code == 200, created.text
        signal_id = created.json()["id"]

        wrong_feed = client.post(
            "/signals/create",
            json={"raw_text": VALID, "feed_id": f1.id, "source_message_id": "99"},
            headers=_headers(p2, k2),
        )
        assert wrong_feed.status_code == 400

        p1_recipients = client.get(
            "/signals/recipients",
            params={"feed_id": f1.id},
            headers=_headers(p1, k1),
        )
        assert p1_recipients.status_code == 200
        assert [row["telegram_user_id"] for row in p1_recipients.json()["recipients"]] == ["101"]

        cross_recipients = client.get(
            "/signals/recipients",
            params={"feed_id": f1.id},
            headers=_headers(p2, k2),
        )
        assert cross_recipients.status_code == 404

        p2_signals = client.get("/providers/me/signals", headers=_headers(p2, k2))
        assert p2_signals.status_code == 200
        assert signal_id not in {row["id"] for row in p2_signals.json()}
    finally:
        security.settings.require_license = False


def test_wrong_provider_api_key_fails_closed(client, db):
    provider, feed, raw_key = _provider_fixture(db, "wrong-key")
    security.settings.require_license = True
    try:
        denied = client.get(
            "/providers/me/feeds",
            headers={"X-Provider-Id": provider.id, "X-Provider-API-Key": raw_key + "x"},
        )
        assert denied.status_code == 401
    finally:
        security.settings.require_license = False


def test_unsubscribed_user_cannot_approve_provider_signal(client, db):
    p1, f1, k1 = _provider_fixture(db, "approval")
    subscribed = register_user(client, "301", "subscribed", "Subscribed")
    outsider = register_user(client, "302", "outsider", "Outsider")
    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, subscribed["id"]))
    db.commit()

    security.settings.require_license = True
    old_registration = security.settings.registration_api_key
    security.settings.registration_api_key = "r" * 40
    try:
        created = client.post(
            "/signals/create",
            json={"raw_text": VALID, "feed_id": f1.id},
            headers=_headers(p1, k1),
        )
        assert created.status_code == 200
        denied = client.post(
            f"/signals/{created.json()['id']}/approve",
            json={"telegram_user_id": outsider["telegram_user_id"]},
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert denied.status_code == 200
        assert denied.json()["result"] == "NOT_SUBSCRIBED"
    finally:
        security.settings.registration_api_key = old_registration
        security.settings.require_license = False


def test_provider_pause_is_execution_kill_path(client, db):
    provider, feed, raw_key = _provider_fixture(db, "pause")
    user = register_user(client, "401", "pause_user", "Pause")
    db_user = db.get(models.User, user["id"])
    crud.subscribe_user_to_feed(db, provider, feed, db_user)
    db.commit()

    security.settings.require_license = True
    old_registration = security.settings.registration_api_key
    security.settings.registration_api_key = "r" * 40
    try:
        created = client.post(
            "/signals/create",
            json={"raw_text": VALID, "feed_id": feed.id},
            headers=_headers(provider, raw_key),
        )
        assert created.status_code == 200
        pause = client.post(
            "/providers/me/pause",
            params={"paused": "true"},
            headers=_headers(provider, raw_key),
        )
        assert pause.status_code == 200
        assert pause.json()["paused"] is True

        decision = client.post(
            f"/signals/{created.json()['id']}/approve",
            json={"telegram_user_id": user["telegram_user_id"]},
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert decision.status_code == 200
        assert decision.json()["result"] == "PROVIDER_PAUSED"
        assert db.query(models.Command).count() == 0
    finally:
        security.settings.registration_api_key = old_registration
        security.settings.require_license = False


def test_provider_command_carries_feed_and_account_ownership(client, db):
    provider, feed, raw_key = _provider_fixture(db, "ownership")
    user = register_user(client, "501", "owner_user", "Owner")
    db_user = db.get(models.User, user["id"])
    subscription, account = crud.subscribe_user_to_feed(db, provider, feed, db_user)
    db.commit()

    security.settings.require_license = True
    old_registration = security.settings.registration_api_key
    security.settings.registration_api_key = "r" * 40
    try:
        created = client.post(
            "/signals/create",
            json={"raw_text": VALID, "feed_id": feed.id},
            headers=_headers(provider, raw_key),
        )
        decision = client.post(
            f"/signals/{created.json()['id']}/approve",
            json={"telegram_user_id": user["telegram_user_id"]},
            headers={"X-Registration-API-Key": "r" * 40},
        )
        assert decision.json()["result"] == "APPROVED"
        command = db.get(models.Command, decision.json()["command_id"])
        assert command.provider_id == provider.id
        assert command.feed_id == feed.id
        assert command.account_id == account.id
        assert subscription.provider_id == provider.id
    finally:
        security.settings.registration_api_key = old_registration
        security.settings.require_license = False
