"""Provider Edition G7 product-surface tests."""
from __future__ import annotations

from app import crud, models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, register_user

VALID_EUR = "EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950"
VALID_GBPJPY = "GBPJPY SELL SL 191.00 TP1 189.00 TP2 188.00"


def _provider(db, slug: str):
    org = crud.create_organization(db, f"{slug} org", f"{slug}-org")
    provider = crud.create_provider(db, org.id, f"{slug} provider", slug)
    feed = crud.create_feed(db, provider, f"{slug} feed", f"{slug}-source")
    _credential, raw_key = crud.issue_provider_credential(db, provider)
    db.commit()
    return provider, feed, raw_key


def _headers(provider, key):
    return {"X-Provider-Id": provider.id, "X-Provider-API-Key": key}


def test_provider_portal_is_served_without_embedded_credentials(client):
    response = client.get("/provider-portal")
    assert response.status_code == 200
    assert "SignalGate Provider Portal" in response.text
    assert "X-Provider-API-Key" in response.text
    assert "sgp_" not in response.text


def test_branding_is_isolated_per_provider(client, db):
    p1, _f1, k1 = _provider(db, "brand-a")
    p2, _f2, k2 = _provider(db, "brand-b")

    update = client.put(
        "/providers/me/branding",
        json={
            "display_name": "Alpha Signals",
            "logo_url": "https://example.test/alpha.svg",
            "primary_color": "#123456",
            "support_contact": "support@example.test",
        },
        headers=_headers(p1, k1),
    )
    assert update.status_code == 200, update.text
    assert update.json()["brand_display_name"] == "Alpha Signals"

    other = client.get("/providers/me", headers=_headers(p2, k2))
    assert other.status_code == 200
    assert other.json()["brand_display_name"] != "Alpha Signals"


def test_provider_can_create_and_configure_own_feed(client, db):
    provider, _feed, key = _provider(db, "policy")
    created = client.post(
        "/providers/me/feeds",
        json={"name": "FX Main", "source_namespace": "telegram-fx"},
        headers=_headers(provider, key),
    )
    assert created.status_code == 200, created.text
    feed_id = created.json()["id"]

    updated = client.put(
        f"/providers/me/feeds/{feed_id}",
        json={
            "allowed_symbols": ["EURUSD", "XAUUSD"],
            "expiry_minutes": 12,
            "default_lot_size": 0.05,
        },
        headers=_headers(provider, key),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["expiry_minutes"] == 12
    assert body["default_lot_size"] == 0.05
    assert "EURUSD" in (body["allowed_symbols_json"] or "")


def test_provider_cannot_configure_another_provider_feed(client, db):
    p1, f1, k1 = _provider(db, "policy-a")
    p2, _f2, k2 = _provider(db, "policy-b")
    response = client.put(
        f"/providers/me/feeds/{f1.id}",
        json={"expiry_minutes": 20},
        headers=_headers(p2, k2),
    )
    assert response.status_code == 404


def test_feed_symbol_policy_drives_parser_and_lot_size(client, db):
    provider, feed, key = _provider(db, "enforced")
    feed = crud.update_feed_policy(
        db,
        feed,
        {
            "allowed_symbols": ["EURUSD"],
            "expiry_minutes": 9,
            "default_lot_size": 0.07,
        },
    )
    user = register_user(client, "811", "policy_user", "Policy")
    crud.subscribe_user_to_feed(db, provider, feed, db.get(models.User, user["id"]))
    db.commit()

    rejected = client.post(
        "/signals/create",
        json={"raw_text": VALID_GBPJPY, "feed_id": feed.id},
        headers=_headers(provider, key),
    )
    assert rejected.status_code == 200
    assert rejected.json()["parser_status"] == "REJECTED"
    assert "not enabled" in (rejected.json()["parser_error"] or "").lower()

    accepted = client.post(
        "/signals/create",
        json={"raw_text": VALID_EUR, "feed_id": feed.id},
        headers=_headers(provider, key),
    )
    assert accepted.status_code == 200
    assert accepted.json()["parser_status"] == "VALID"

    decision = client.post(
        f"/signals/{accepted.json()['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    ).json()
    assert decision["result"] == "APPROVED"
    command = db.get(models.Command, decision["command_id"])
    assert command.lot_size == 0.07
    assert command.feed_id == feed.id


def test_provider_credential_rotation_revokes_previous_key(client, db):
    provider, _feed, old_key = _provider(db, "rotate")
    rotated = client.post(
        "/providers/me/credentials/rotate",
        headers=_headers(provider, old_key),
    )
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != old_key

    old = client.get("/providers/me", headers=_headers(provider, old_key))
    assert old.status_code == 401
    new = client.get("/providers/me", headers=_headers(provider, new_key))
    assert new.status_code == 200


def test_demo_tenant_bootstrap_is_reusable_but_key_is_fresh(client):
    first = client.post("/admin/demo-tenant", headers=ADMIN_HEADERS)
    second = client.post("/admin/demo-tenant", headers=ADMIN_HEADERS)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    a, b = first.json(), second.json()
    assert a["provider_id"] == b["provider_id"]
    assert a["feed_id"] == b["feed_id"]
    assert a["user_id"] == b["user_id"]
    assert a["provider_api_key"] != b["provider_api_key"]


def test_provider_history_is_tenant_scoped(client, db):
    p1, f1, k1 = _provider(db, "history-a")
    p2, _f2, k2 = _provider(db, "history-b")
    user = register_user(client, "812", "history_user", "History")
    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, user["id"]))
    db.commit()

    signal = client.post(
        "/signals/create",
        json={"raw_text": VALID_EUR, "feed_id": f1.id},
        headers=_headers(p1, k1),
    ).json()
    decision = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    ).json()
    assert decision["result"] == "APPROVED"

    own = client.get("/providers/me/history", headers=_headers(p1, k1))
    other = client.get("/providers/me/history", headers=_headers(p2, k2))
    assert decision["command_id"] in {row["command_id"] for row in own.json()["history"]}
    assert decision["command_id"] not in {row["command_id"] for row in other.json()["history"]}
