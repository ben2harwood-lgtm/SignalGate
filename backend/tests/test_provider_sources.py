"""Tenant-bound Telegram provider source tests."""
from __future__ import annotations

import datetime as dt
import io
import os
from pathlib import Path

import pytest

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


def _source_claim(binding):
    """Constrain hosted signal creation to the original source snapshot."""
    return {
        "expected_binding_id": binding["binding_id"],
        "expected_provider_id": binding["provider_id"],
        "expected_feed_id": binding["feed_id"],
    }


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


def test_source_status_returns_effective_expiry_for_bot(client, db):
    from app.config import get_settings

    provider, feed, key = _provider(db, "source-expiry-default")
    feed.expiry_minutes = 17
    db.commit()
    invite = _source_invite(client, provider, feed, key)
    connected = _connect(client, invite, "9209")
    assert connected.status_code == 200, connected.text

    def read_status():
        response = client.get(
            "/provider-sources/telegram/status",
            params={"telegram_user_id": "9209"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert read_status()["expiry_minutes"] == 17

    # With no feed override, status must report the same default used by
    # create_signal, including a persisted operator-managed setting.
    feed.expiry_minutes = None
    db.commit()
    configured_default = get_settings().default_signal_expiry_minutes
    assert read_status()["expiry_minutes"] == configured_default

    crud.set_setting(db, "default_signal_expiry_minutes", "23")
    db.commit()
    assert read_status()["expiry_minutes"] == 23

    # The persisted signal deadline must use the same effective value that
    # the Telegram status receipt advertises to the human approval card.
    signal_response = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9209",
            "raw_text": EUR_BUY,
            "source_message_id": "9209:db-default-expiry",
            **_source_claim(connected.json()),
        },
    )
    assert signal_response.status_code == 200, signal_response.text
    signal = signal_response.json()
    created_at = dt.datetime.fromisoformat(signal["created_at"])
    expires_at = dt.datetime.fromisoformat(signal["expires_at"])
    assert abs((expires_at - created_at).total_seconds() - 23 * 60) < 5


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
    # A recipient lookup after rebind must identify the NEW tenant/feed,
    # never silently return that list as if it belonged to the old source.
    scoped = client.get(
        "/provider-sources/telegram/recipients",
        params={"telegram_user_id": "9202"},
    )
    assert scoped.status_code == 200
    assert scoped.json()["binding_id"] == b.json()["binding_id"]
    assert scoped.json()["provider_id"] == p2.id
    assert scoped.json()["feed_id"] == f2.id
    assert scoped.json()["provider_id"] != p1.id

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


def test_rebind_refuses_stale_source_claim_before_cross_tenant_signal_write(client, db):
    """An A snapshot may not be stored under B after a source identity rebind."""
    p1, f1, k1 = _provider(db, "stale-create-a")
    p2, f2, k2 = _provider(db, "stale-create-b")
    old = _connect(client, _source_invite(client, p1, f1, k1), "9374")
    assert old.status_code == 200, old.text
    a_scope = _source_claim(old.json())
    new = _connect(client, _source_invite(client, p2, f2, k2), "9374")
    assert new.status_code == 200, new.text
    # Rebind reuses the same binding ID, so feed and provider must ALSO match.
    assert old.json()["binding_id"] == new.json()["binding_id"]
    assert a_scope["expected_feed_id"] != new.json()["feed_id"]

    source_text = "EURUSD BUY SL 1.0800 TP1 1.0900"
    payload = {
        "telegram_user_id": "9374",
        "raw_text": source_text,
        "source_message_id": "9374:stale-preview",
        **a_scope,
    }
    stale = client.post("/provider-sources/telegram/signals", json=payload)
    assert stale.status_code == 409, stale.text
    assert db.query(models.Signal).count() == 0
    assert db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "SIGNAL_CREATED"
    ).count() == 0

    # A missing scope cannot become an implicit trust-the-current-source mode.
    missing = {k: v for k, v in payload.items() if not k.startswith("expected_")}
    refused = client.post("/provider-sources/telegram/signals", json=missing)
    assert refused.status_code == 422, refused.text
    assert db.query(models.Signal).count() == 0

    # Current B binding still works and preserves its own provider/feed.
    current = client.post(
        "/provider-sources/telegram/signals",
        json={**payload, **_source_claim(new.json())},
    )
    assert current.status_code == 200, current.text
    assert current.json()["provider_id"] == p2.id
    assert current.json()["feed_id"] == f2.id
    assert current.json()["newly_created"] is True
    assert db.query(models.Signal).count() == 1


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
            **_source_claim(binding),
        },
    )
    assert valid.status_code == 200, valid.text
    signal = valid.json()
    assert signal["provider_id"] == provider.id
    assert signal["feed_id"] == feed.id
    assert signal["parser_status"] == "VALID"
    assert signal["newly_created"] is True
    assert signal["source"] == f"FEED:{feed.id}:TELEGRAM_BINDING:{binding['binding_id']}"

    blocked = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9204",
            "raw_text": GBPJPY_SELL,
            "source_message_id": "chat:102",
            **_source_claim(binding),
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["newly_created"] is True
    assert blocked.json()["parser_status"] == "REJECTED"
    assert "not enabled" in (blocked.json()["parser_error"] or "").lower()

    duplicate = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9204",
            "raw_text": EUR_BUY,
            "source_message_id": "chat:101",
            **_source_claim(binding),
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == signal["id"]
    assert duplicate.json()["newly_created"] is False

    conflict = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9204",
            "raw_text": "EURUSD BUY SL 1.0790 TP1 1.0910",
            "source_message_id": "chat:101",
            **_source_claim(binding),
        },
    )
    assert conflict.status_code == 409




def test_bound_source_creation_marker_requires_id_and_closes_insert_race(
    client, db, monkeypatch
):
    """Only an inserted signal earns a fresh marker, even after unique-key races."""
    provider, feed, key = _provider(db, "source-race-marker")
    invite = _source_invite(client, provider, feed, key)
    binding = _connect(client, invite, "9371").json()
    payload = {
        "telegram_user_id": "9371",
        "raw_text": EUR_BUY,
        "source_message_id": "9371:durable-id",
        **_source_claim(binding),
    }
    # A missing/empty message identity cannot bypass hosted replay protection.
    for invalid in ({k: v for k, v in payload.items() if k != "source_message_id"},
                    {**payload, "source_message_id": ""}):
        response = client.post("/provider-sources/telegram/signals", json=invalid)
        assert response.status_code == 422
    assert db.query(models.Signal).count() == 0

    initial = client.post("/provider-sources/telegram/signals", json=payload)
    assert initial.status_code == 200, initial.text
    assert initial.json()["newly_created"] is True
    assert client.post(
        "/provider-sources/telegram/signals", json=payload
    ).json()["newly_created"] is False

    # Simulate two workers: the first unique-key precheck observes a stale
    # absence even though the competing worker already committed the row.
    # The database uniqueness constraint must still return replay=False.
    scalar = db.scalar
    saw_stale_precheck = False

    def stale_precheck(statement, *args, **kwargs):
        nonlocal saw_stale_precheck
        if (not saw_stale_precheck
                and "signals.source_message_id" in str(statement)):
            saw_stale_precheck = True
            return None
        return scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", stale_precheck)
    raced, freshly_created = crud.create_signal_with_freshness(
        db,
        raw_text=EUR_BUY,
        source=f"TELEGRAM_BINDING:{binding['binding_id']}",
        source_message_id=payload["source_message_id"],
        provider_id=provider.id,
        feed_id=feed.id,
    )
    assert saw_stale_precheck
    assert raced.id == initial.json()["id"]
    assert freshly_created is False
    db.commit()
    assert db.query(models.Signal).filter(
        models.Signal.source == initial.json()["source"],
        models.Signal.source_message_id == payload["source_message_id"],
    ).count() == 1



@pytest.mark.parametrize(
    "competing_raw_text, expect_conflict",
    [
        (EUR_BUY, False),
        ("EURUSD BUY SL 1.0750 TP1 1.0900", True),
    ],
    ids=["identical-message-replay", "conflicting-message-content"],
)
def test_provider_source_concurrent_replay_freshness_postgresql(
    client, db, competing_raw_text, expect_conflict
):
    """Real two-connection races: replay is not fresh; changed text conflicts."""
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.database import SessionLocal

    provider, feed, key = _provider(db, "source-concurrent-freshness")
    invite = _source_invite(client, provider, feed, key)
    binding = _connect(client, invite, "9372")
    assert binding.status_code == 200, binding.text
    args = {
        "raw_text": EUR_BUY,
        "source": f"TELEGRAM_BINDING:{binding.json()['binding_id']}",
        "source_message_id": "9372:one-message",
        "provider_id": provider.id,
        "feed_id": feed.id,
    }
    precheck_completed = Event()
    first_session = SessionLocal()
    try:
        first, first_fresh = crud.create_signal_with_freshness(
            first_session, **args
        )
        assert first_fresh is True
        first_id = first.id
        # Leave this first insert uncommitted. The second transaction must
        # observe absence, then lose to the database uniqueness constraint.
        def competitor():
            with SessionLocal() as second:
                # A Future timeout does not terminate a DB-blocked worker:
                # bound waits inside PostgreSQL to ensure CI can fail cleanly.
                connection = second.connection()
                connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                original_scalar = second.scalar

                def observe_precheck(statement, *scalar_args, **scalar_kwargs):
                    value = original_scalar(
                        statement, *scalar_args, **scalar_kwargs
                    )
                    if (
                        not precheck_completed.is_set()
                        and "signals.source_message_id" in str(statement)
                    ):
                        assert value is None
                        precheck_completed.set()
                    return value

                second.scalar = observe_precheck
                if expect_conflict:
                    # The same source/message ID with different text must
                    # fail even when both workers observed an empty precheck.
                    with pytest.raises(crud.SignalReplayConflict):
                        crud.create_signal_with_freshness(
                            second, **{**args, "raw_text": competing_raw_text}
                        )
                    second.commit()
                    return None, False
                competing, fresh = crud.create_signal_with_freshness(
                    second, **{**args, "raw_text": competing_raw_text}
                )
                second.commit()
                return competing.id, fresh

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competitor)
            try:
                assert precheck_completed.wait(timeout=10), (
                    "Competing PostgreSQL transaction did not reach precheck"
                )
            finally:
                # Unblock the uniqueness check even if the assertion fails.
                first_session.commit()
            competitor_id, competitor_fresh = future.result(timeout=20)

        db.expire_all()
        if expect_conflict:
            assert competitor_id is None and competitor_fresh is False
            assert db.query(models.AuditLog).filter(
                models.AuditLog.event_type == "SIGNAL_REPLAY_CONFLICT",
                models.AuditLog.entity_id == first_id,
            ).count() == 1
        else:
            assert competitor_id == first_id
            assert competitor_fresh is False
        assert db.query(models.Signal).filter(
            models.Signal.source == f"FEED:{feed.id}:{args['source']}",
            models.Signal.source_message_id == args["source_message_id"],
        ).count() == 1
    finally:
        first_session.close()



def test_provider_source_rolled_back_creator_allows_fresh_competitor_postgresql(
    client, db
):
    """A failed creator must not suppress a competing, newly committed signal.

    Two real database transactions must agree that only a durable insert earns
    the fresh marker. The first worker inserts but aborts without committing;
    the competing worker must insert successfully and remain broadcastable.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.database import SessionLocal

    provider, feed, key = _provider(db, "source-rolled-back-creator")
    invite = _source_invite(client, provider, feed, key)
    binding = _connect(client, invite, "9373")
    assert binding.status_code == 200, binding.text
    args = {
        "raw_text": EUR_BUY,
        "source": f"TELEGRAM_BINDING:{binding.json()['binding_id']}",
        "source_message_id": "9373:aborted-creator",
        "provider_id": provider.id,
        "feed_id": feed.id,
    }
    precheck_completed = Event()
    first_session = SessionLocal()
    try:
        uncommitted, initially_fresh = crud.create_signal_with_freshness(
            first_session, **args
        )
        assert initially_fresh is True
        assert uncommitted.id

        def competitor():
            with SessionLocal() as second:
                # A Future timeout does not terminate a DB-blocked worker:
                # bound waits inside PostgreSQL to ensure CI can fail cleanly.
                connection = second.connection()
                connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                original_scalar = second.scalar

                def observe_precheck(statement, *scalar_args, **scalar_kwargs):
                    value = original_scalar(
                        statement, *scalar_args, **scalar_kwargs
                    )
                    if (
                        not precheck_completed.is_set()
                        and "signals.source_message_id" in str(statement)
                    ):
                        assert value is None
                        precheck_completed.set()
                    return value

                second.scalar = observe_precheck
                created, fresh = crud.create_signal_with_freshness(
                    second, **args
                )
                second.commit()
                return created.id, fresh

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competitor)
            try:
                assert precheck_completed.wait(timeout=10), (
                    "Competing PostgreSQL creator did not reach precheck"
                )
            finally:
                # Simulate process failure before its transaction commits.
                # Unblock the competing insert even if the assertion fails.
                first_session.rollback()
            committed_id, committed_fresh = future.result(timeout=20)

        assert committed_fresh is True
        db.expire_all()
        stored = db.query(models.Signal).filter(
            models.Signal.source == f"FEED:{feed.id}:{args['source']}",
            models.Signal.source_message_id == args["source_message_id"],
        ).all()
        assert len(stored) == 1
        assert stored[0].id == committed_id
        assert db.query(models.AuditLog).filter(
            models.AuditLog.event_type == "SIGNAL_CREATED",
            models.AuditLog.entity_id == committed_id,
        ).count() == 1
    finally:
        first_session.rollback()
        first_session.close()


def test_bound_source_duplicate_replay_expires_stale_signal_once(client, db):
    """A replay must not renew or expose a VALID-looking expired ledger row."""
    provider, feed, key = _provider(db, "source-expiry-replay")
    crud.update_feed_policy(
        db, feed, {"allowed_symbols": ["EURUSD"], "expiry_minutes": 11}
    )
    db.commit()
    invite = _source_invite(client, provider, feed, key)
    connected = _connect(client, invite, "9360")
    assert connected.status_code == 200, connected.text
    payload = {
        "telegram_user_id": "9360",
        "raw_text": EUR_BUY,
        "source_message_id": "9360:replay",
        **_source_claim(connected.json()),
    }
    first = client.post("/provider-sources/telegram/signals", json=payload)
    assert first.status_code == 200, first.text
    signal_id = first.json()["id"]
    source = first.json()["source"]
    assert first.json()["status"] == "VALID"
    assert first.json()["newly_created"] is True

    # The deadline can elapse before any other route has refreshed the row.
    signal = db.get(models.Signal, signal_id)
    expired_at = crud.utcnow() - dt.timedelta(minutes=2)
    signal.expires_at = expired_at
    db.commit()
    assert signal.status == "VALID"

    for _ in range(2):
        replay = client.post("/provider-sources/telegram/signals", json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == signal_id
        assert replay.json()["newly_created"] is False
        assert replay.json()["source"] == source
        assert replay.json()["parser_status"] == "VALID"
        assert replay.json()["status"] == "EXPIRED"

    db.expire_all()
    stored = db.get(models.Signal, signal_id)
    assert stored.status == "EXPIRED"
    assert stored.expires_at == expired_at  # replay must not renew expiry
    assert db.query(models.Signal).filter(
        models.Signal.source == source,
        models.Signal.source_message_id == payload["source_message_id"],
    ).count() == 1
    assert db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "SIGNAL_EXPIRED",
        models.AuditLog.entity_id == signal_id,
    ).count() == 1


def test_bound_source_recipients_are_only_that_feeds_consented_subscribers(client, db):
    p1, f1, k1 = _provider(db, "recipients-a")
    p2, f2, _k2 = _provider(db, "recipients-b")
    u1 = register_user(client, "9205", "feed_a", "Feed A")
    u2 = register_user(client, "9206", "feed_b", "Feed B")
    u3 = register_user(client, "not-a-chat-id", "non_numeric", "Non Numeric")
    max_user = register_user(client, "4503599627370495", "max_direct_id", "Max Direct")
    invalid_users = [
        register_user(client, value, f"invalid_direct_{i}", "Invalid Direct")
        for i, value in enumerate((
            "-1001234567890", "0", "09205", "4503599627370496",
            "12345678901234567", "１２３４",
        ))
    ]

    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, u1["id"]))
    crud.subscribe_user_to_feed(db, p2, f2, db.get(models.User, u2["id"]))
    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, u3["id"]))
    crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, max_user["id"]))
    for invalid_user in invalid_users:
        crud.subscribe_user_to_feed(db, p1, f1, db.get(models.User, invalid_user["id"]))
    db.commit()

    invite = _source_invite(client, p1, f1, k1)
    _connect(client, invite, "9207")

    response = client.get(
        "/provider-sources/telegram/recipients",
        params={"telegram_user_id": "9207"},
    )
    assert response.status_code == 200
    assert response.json()["provider_id"] == p1.id
    assert response.json()["feed_id"] == f1.id
    ids = {x["telegram_user_id"] for x in response.json()["recipients"]}
    assert ids == {"9205", "4503599627370495"}


def test_bound_source_recipients_refuse_pause_after_source_connect(client, db):
    """A pause between signal storage and recipient lookup cannot broadcast."""
    provider, feed, key = _provider(db, "recipients-pause")
    crud.update_feed_policy(db, feed, {"allowed_symbols": ["EURUSD"]})
    db.commit()
    subscriber = register_user(client, "9358", "paused_user", "Paused User")
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber["id"])
    )
    db.commit()
    invite = _source_invite(client, provider, feed, key)
    connected = _connect(client, invite, "9359")
    assert connected.status_code == 200, connected.text
    stored = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9359",
            "raw_text": EUR_BUY,
            "source_message_id": "9359:1",
            **_source_claim(connected.json()),
        },
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["parser_status"] == "VALID"
    assert stored.json()["provider_id"] == provider.id
    assert stored.json()["feed_id"] == feed.id

    def lookup():
        return client.get(
            "/provider-sources/telegram/recipients",
            params={"telegram_user_id": "9359"},
        )

    before = lookup()
    assert before.status_code == 200
    assert [r["telegram_user_id"] for r in before.json()["recipients"]] == ["9358"]
    for paused_scope in (feed, provider):
        paused_scope.paused = True
        db.commit()
        denied = lookup()
        assert denied.status_code == 403
        assert "paused" in denied.json()["detail"].lower()
        paused_scope.paused = False
        db.commit()
    after = lookup()
    assert after.status_code == 200
    assert [r["telegram_user_id"] for r in after.json()["recipients"]] == ["9358"]


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
                    **_source_claim({"binding_id": "ABSENT", "provider_id": "ABSENT", "feed_id": "ABSENT"}),
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
            **_source_claim(connected),
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
                **_source_claim(allowed.json()),
            },
        )
        assert no_secret.status_code == 401
        with_secret = client.post(
            "/provider-sources/telegram/signals",
            json={
                "telegram_user_id": "9211",
                "raw_text": EUR_BUY,
                "source_message_id": "1",
                **_source_claim(allowed.json()),
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
    assert "/provider-sources/telegram/extract" in handler_source
    assert '"/provider-sources/telegram/recipients"' in handler_source
