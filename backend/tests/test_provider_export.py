"""Provider evidence export isolation and privacy tests."""
from __future__ import annotations

from app import crud, models

from .conftest import register_user

VALID = "EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950"


def _provider(db, slug: str):
    org = crud.create_organization(db, f"{slug} org", f"{slug}-org")
    provider = crud.create_provider(db, org.id, f"{slug} provider", slug)
    feed = crud.create_feed(db, provider, f"{slug} feed", f"{slug}-source")
    _credential, raw_key = crud.issue_provider_credential(db, provider)
    db.commit()
    return provider, feed, raw_key


def _headers(provider, key):
    return {"X-Provider-Id": provider.id, "X-Provider-API-Key": key}


def test_provider_export_contains_own_operating_evidence_only(client, db):
    p1, f1, k1 = _provider(db, "export-a")
    p2, f2, k2 = _provider(db, "export-b")
    u1 = register_user(client, "9401", "alpha", "Alpha")
    u2 = register_user(client, "9402", "beta", "Beta")
    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, u1["id"]))
    crud.subscribe_user_to_feed(db, p2, f2, db.get(models.User, u2["id"]))
    db.commit()

    s1 = client.post(
        "/signals/create",
        json={"raw_text": VALID, "feed_id": f1.id},
        headers=_headers(p1, k1),
    ).json()
    s2 = client.post(
        "/signals/create",
        json={"raw_text": VALID, "feed_id": f2.id},
        headers=_headers(p2, k2),
    ).json()

    r1 = client.get("/providers/me/export", headers=_headers(p1, k1))
    assert r1.status_code == 200, r1.text
    assert "attachment" in r1.headers["content-disposition"].lower()
    body = r1.json()

    assert body["schema"] == "signalgate-provider-evidence-v1"
    assert body["provider"]["id"] == p1.id
    assert {feed["id"] for feed in body["feeds"]} == {f1.id}
    assert s1["id"] in {row["id"] for row in body["signals"]}
    assert s2["id"] not in {row["id"] for row in body["signals"]}
    assert u1["telegram_user_id"] in {
        subscriber["telegram_user_id"]
        for feed in body["feeds"]
        for subscriber in feed["subscribers"]
    }
    assert u2["telegram_user_id"] not in {
        subscriber["telegram_user_id"]
        for feed in body["feeds"]
        for subscriber in feed["subscribers"]
    }


def test_provider_export_never_contains_raw_credentials_or_raw_signal_text(client, db):
    provider, feed, key = _provider(db, "export-secrets")
    user = register_user(client, "9403", "secret_user", "Secret")
    crud.subscribe_user_to_feed(db, provider, feed, db.get(models.User, user["id"]))
    db.commit()

    raw_text = VALID + " PROVIDER_PRIVATE_NOTE_SHOULD_NOT_EXPORT"
    created = client.post(
        "/signals/create",
        json={"raw_text": raw_text, "feed_id": feed.id},
        headers=_headers(provider, key),
    )
    assert created.status_code == 200

    response = client.get("/providers/me/export", headers=_headers(provider, key))
    serialized = response.text
    assert key not in serialized
    assert user["license_key"] not in serialized
    assert "PROVIDER_PRIVATE_NOTE_SHOULD_NOT_EXPORT" not in serialized
    assert "key_hash" not in serialized
    assert "license_key_hash" not in serialized
    assert "provider_api_key" not in serialized


def test_provider_export_requires_valid_provider_credential(client, db):
    provider, _feed, key = _provider(db, "export-auth")
    denied = client.get("/providers/me/export")
    assert denied.status_code in {401, 403}
    wrong = client.get(
        "/providers/me/export",
        headers=_headers(provider, key + "wrong"),
    )
    assert wrong.status_code == 401
    allowed = client.get("/providers/me/export", headers=_headers(provider, key))
    assert allowed.status_code == 200


def test_provider_portal_exposes_evidence_download_control(client):
    response = client.get("/provider-portal")
    assert response.status_code == 200
    assert 'id="downloadEvidence"' in response.text
    assert '"/providers/me/export"' in response.text
