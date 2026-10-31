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


@pytest.mark.parametrize("competing_action", ["connect", "revoke"])
def test_source_invite_concurrent_claim_or_revoke_postgresql(
    client, db, competing_action
):
    """Only one claimant wins, and a concurrent revoke cannot undo acceptance.

    These are two distinct PostgreSQL transactions. The first has accepted
    an invite but has not committed; the second starts while that row is
    still locked. Neither synthetic client ever contacts Telegram or MT5.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import sleep

    from sqlalchemy import event
    from app.database import SessionLocal

    provider, feed, key = _provider(db, f"source-once-{competing_action}")
    provider_id = provider.id
    invite = _source_invite(client, provider, feed, key)
    invite_id = invite["invite_id"]
    token = invite["connection_token"]
    invite_read_started = Event()
    invite_read_finished = Event()

    def competitor():
        with SessionLocal() as second:
            # A future timeout cannot terminate a PostgreSQL lock waiter:
            # bound waits at the database level even if this test regresses.
            connection = second.connection()
            connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            def observe_sql(_conn, _cursor, statement, _params, _ctx, _many):
                if "FROM provider_source_invites" in statement:
                    invite_read_started.set()

            event.listen(connection, "before_cursor_execute", observe_sql)
            original_scalar = second.scalar

            def observe_scalar(statement, *args, **kwargs):
                value = original_scalar(statement, *args, **kwargs)
                if "provider_source_invites" in str(statement):
                    invite_read_finished.set()
                return value

            second.scalar = observe_scalar
            try:
                if competing_action == "connect":
                    crud.connect_telegram_provider_source(second, token, "98002")
                else:
                    crud.revoke_provider_source_invite(
                        second, provider_id, invite_id
                    )
            except ValueError as exc:
                second.rollback()
                return str(exc)
            second.commit()
            return "UNEXPECTED_SUCCESS"

    with SessionLocal() as first:
        crud.connect_telegram_provider_source(first, token, "98001")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competitor)
            try:
                assert invite_read_started.wait(timeout=5), (
                    "Competing PostgreSQL transaction did not reach invite SELECT"
                )
                # A missing FOR UPDATE lets the second worker read PENDING
                # before the first commit, even if a later UPDATE/audit blocks.
                # Prove that the invite SELECT itself is held by our row lock.
                sleep(0.2)
                assert not invite_read_finished.is_set(), (
                    "Competing invite read escaped the uncommitted row lock"
                )
            finally:
                first.commit()
            outcome = future.result(timeout=18)
            assert invite_read_finished.is_set()

    expected = (
        "Source invite is no longer active"
        if competing_action == "connect"
        else "Accepted source invite cannot be revoked"
    )
    assert outcome == expected
    with SessionLocal() as check:
        stored = check.get(models.ProviderSourceInvite, invite_id)
        assert stored.status == "ACCEPTED"
        assert stored.accepted_telegram_user_id == "98001"
        bindings = (
            check.query(models.ProviderSourceBinding)
            .filter(models.ProviderSourceBinding.external_identity.in_(
                ["98001", "98002"]
            ))
            .all()
        )
        assert len(bindings) == 1
        assert bindings[0].external_identity == "98001"


def test_distinct_invites_first_binding_serializes_postgresql(client, db):
    """Two provider invites cannot concurrently INSERT the same new source.

    The unique constraint prevents duplicate committed rows but does not
    serialize the first, previously absent identity. Both valid invitations
    should complete without an unhandled integrity error. No broker is used.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import sleep

    from sqlalchemy import event
    from app.database import SessionLocal

    first_provider, first_feed, first_key = _provider(db, "first-new-identity")
    next_provider, next_feed, next_key = _provider(db, "second-new-identity")
    first_invite = _source_invite(client, first_provider, first_feed, first_key)
    next_invite = _source_invite(client, next_provider, next_feed, next_key)
    first_invite_id, next_invite_id = first_invite["invite_id"], next_invite["invite_id"]
    next_provider_id = next_provider.id
    identity = "98004"
    lock_started, lock_finished = Event(), Event()

    def competing_first_binding():
        with SessionLocal() as second:
            connection = second.connection()
            connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            def before_sql(_conn, _cursor, statement, _params, _ctx, _many):
                if "pg_advisory_xact_lock" in statement:
                    lock_started.set()

            def after_sql(_conn, _cursor, statement, _params, _ctx, _many):
                if "pg_advisory_xact_lock" in statement:
                    lock_finished.set()

            event.listen(connection, "before_cursor_execute", before_sql)
            event.listen(connection, "after_cursor_execute", after_sql)
            crud.connect_telegram_provider_source(
                second, next_invite["connection_token"], identity
            )
            second.commit()
            return "ACCEPTED"

    with SessionLocal() as first:
        crud.connect_telegram_provider_source(
            first, first_invite["connection_token"], identity
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competing_first_binding)
            try:
                assert lock_started.wait(timeout=5), (
                    "Competing first-bind did not attempt the identity lock"
                )
                sleep(0.2)
                assert not lock_finished.is_set(), (
                    "Second first-bind escaped the uncommitted source-identity lock"
                )
            finally:
                first.commit()
            assert future.result(timeout=18) == "ACCEPTED"

    assert lock_finished.is_set()
    with SessionLocal() as check:
        first_stored = check.get(models.ProviderSourceInvite, first_invite_id)
        next_stored = check.get(models.ProviderSourceInvite, next_invite_id)
        assert first_stored.status == next_stored.status == "ACCEPTED"
        assert first_stored.accepted_telegram_user_id == identity
        assert next_stored.accepted_telegram_user_id == identity
        bindings = check.query(models.ProviderSourceBinding).filter(
            models.ProviderSourceBinding.source_type == "TELEGRAM",
            models.ProviderSourceBinding.external_identity == identity,
        ).all()
        assert len(bindings) == 1
        assert bindings[0].provider_id == next_provider_id
        assert bindings[0].status == "ACTIVE"
        assert check.query(models.AuditLog).filter(
            models.AuditLog.entity_id == bindings[0].id,
            models.AuditLog.event_type == "PROVIDER_SOURCE_CONNECTED",
        ).count() == 2


def test_rebind_blocks_stale_provider_revocation_postgresql(client, db):
    """A previously owning provider cannot revoke a newly rebound source.

    This interleaves separate PostgreSQL transactions; a stale owner attempts
    to revoke while the new provider's rebind remains uncommitted. It does not
    send Telegram messages, connect to a broker, or execute an order.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import sleep

    from sqlalchemy import event
    from app.database import SessionLocal

    old_provider, old_feed, old_key = _provider(db, "stale-binding-owner")
    new_provider, new_feed, new_key = _provider(db, "new-binding-owner")
    old_id, new_id, new_feed_id = old_provider.id, new_provider.id, new_feed.id
    old_invite = _source_invite(client, old_provider, old_feed, old_key)
    original = _connect(client, old_invite, "98003")
    assert original.status_code == 200, original.text
    binding_id = original.json()["binding_id"]
    new_invite = _source_invite(client, new_provider, new_feed, new_key)

    binding_read_started = Event()
    binding_read_finished = Event()

    def stale_owner_revoke():
        with SessionLocal() as competing:
            connection = competing.connection()
            connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            def observe_sql(_conn, _cursor, statement, _params, _ctx, _many):
                if "FROM provider_source_bindings" in statement:
                    binding_read_started.set()

            event.listen(connection, "before_cursor_execute", observe_sql)
            original_scalar = competing.scalar

            def observe_scalar(statement, *args, **kwargs):
                result = original_scalar(statement, *args, **kwargs)
                if "provider_source_bindings" in str(statement):
                    binding_read_finished.set()
                return result

            competing.scalar = observe_scalar
            try:
                crud.revoke_provider_source_binding(competing, old_id, binding_id)
            except ValueError as exc:
                competing.rollback()
                return str(exc)
            competing.commit()
            return "UNEXPECTED_SUCCESS"

    with SessionLocal() as first:
        crud.connect_telegram_provider_source(
            first, new_invite["connection_token"], "98003"
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale_owner_revoke)
            try:
                assert binding_read_started.wait(timeout=5), (
                    "Stale revoke did not reach the binding SELECT"
                )
                sleep(0.2)
                assert not binding_read_finished.is_set(), (
                    "Stale revoke read the old owner despite an in-flight rebind"
                )
            finally:
                first.commit()
            outcome = future.result(timeout=18)

    assert outcome == "Source binding not found"
    assert binding_read_finished.is_set()
    with SessionLocal() as check:
        binding = check.get(models.ProviderSourceBinding, binding_id)
        assert binding.provider_id == new_id
        assert binding.feed_id == new_feed_id
        assert binding.external_identity == "98003"
        assert binding.status == "ACTIVE"
        assert (
            check.query(models.AuditLog)
            .filter(
                models.AuditLog.entity_id == binding_id,
                models.AuditLog.event_type == "PROVIDER_SOURCE_REVOKED",
            )
            .count()
            == 0
        )


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


def test_hosted_signal_post_pins_source_binding(client, db, monkeypatch):
    """The write route must request a locked source snapshot, not a plain GET."""
    provider, feed, key = _provider(db, "source-post-lock")
    connected = _connect(
        client, _source_invite(client, provider, feed, key), "9381"
    )
    assert connected.status_code == 200, connected.text
    observed = []
    original = crud.get_telegram_provider_source

    def checked_source(session, telegram_user_id, **options):
        observed.append(options.get("lock_for_update"))
        return original(session, telegram_user_id, **options)

    monkeypatch.setattr(crud, "get_telegram_provider_source", checked_source)
    submitted = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": "9381",
            "raw_text": EUR_BUY,
            "source_message_id": "9381:lock-contract",
            **_source_claim(connected.json()),
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["newly_created"] is True
    assert observed == [True]


def test_source_binding_lock_serializes_postgresql_rebind(client, db):
    """A competing source rebind must wait until the signal transaction ends."""
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-level lock proof")

    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    from app.database import SessionLocal

    provider, feed, key = _provider(db, "source-lock-rebind")
    connected = _connect(
        client, _source_invite(client, provider, feed, key), "9382"
    )
    assert connected.status_code == 200, connected.text
    binding_id = connected.json()["binding_id"]
    statement = (
        update(models.ProviderSourceBinding)
        .where(models.ProviderSourceBinding.id == binding_id)
        .values(status="REVOKED")
    )
    with SessionLocal() as creator:
        source = crud.get_telegram_provider_source(
            creator, "9382", lock_for_update=True
        )
        assert source is not None and source[0].id == binding_id
        with SessionLocal() as rebind:
            rebind.connection().exec_driver_sql(
                "SET LOCAL lock_timeout = '1500ms'"
            )
            with pytest.raises(DBAPIError) as blocked:
                rebind.execute(statement)
            assert getattr(blocked.value.orig, "pgcode", None) == "55P03"
            rebind.rollback()
        creator.commit()

    # Once the source-creation transaction commits, a rebind can proceed.
    # Roll it back so this test never leaves a revoked source behind.
    with SessionLocal() as rebind:
        rebind.execute(statement)
        rebind.rollback()
    assert crud.get_telegram_provider_source(db, "9382") is not None


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
    connected = _connect(client, invite, "9208").json()

    os.environ.pop("FAKE_EXTRACTOR_TEXT", None)
    rejected = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": "9208", **_source_claim(connected)},
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
        params={"telegram_user_id": "9208", **_source_claim(connected)},
        files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert accepted.status_code == 200
    assert accepted.json()["parser_status"] == "VALID"


def test_rebind_refuses_stale_screenshot_scope_before_extraction(client, db, monkeypatch):
    """Do not parse source A's private image using a rebound provider B feed."""
    provider_a, feed_a, key_a = _provider(db, "image-rebind-a")
    provider_b, feed_b, key_b = _provider(db, "image-rebind-b")
    original = _connect(
        client, _source_invite(client, provider_a, feed_a, key_a), "9391"
    ).json()
    rebound = _connect(
        client, _source_invite(client, provider_b, feed_b, key_b), "9391"
    ).json()
    assert original["binding_id"] == rebound["binding_id"]
    assert original["feed_id"] != rebound["feed_id"]

    def forbidden_extractor():
        raise AssertionError("stale screenshot reached the image extractor")

    before = db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED"
    ).count()
    with monkeypatch.context() as patcher:
        patcher.setattr(
            "app.routes.provider_sources.get_extractor", forbidden_extractor
        )
        stale = client.post(
            "/provider-sources/telegram/extract",
            params={"telegram_user_id": "9391", **_source_claim(original)},
            files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
        )
        assert stale.status_code == 409, stale.text

        omitted = client.post(
            "/provider-sources/telegram/extract",
            params={"telegram_user_id": "9391"},
            files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
        )
        assert omitted.status_code == 422, omitted.text

    assert db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED"
    ).count() == before
    accepted = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": "9391", **_source_claim(rebound)},
        files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert accepted.status_code == 200, accepted.text
    assert db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED"
    ).count() == before + 1



def test_rebind_during_extraction_refuses_result_and_audit_postgresql(
    client, db, monkeypatch
):
    """A separate PostgreSQL writer can rebind the source during extractor I/O."""
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from types import SimpleNamespace

    from app.database import SessionLocal

    provider_a, feed_a, key_a = _provider(db, "extract-inflight-a")
    provider_b, feed_b, _key_b = _provider(db, "extract-inflight-b")
    original = _connect(
        client, _source_invite(client, provider_a, feed_a, key_a), "9392"
    ).json()
    calls = []

    class RebindingExtractor:
        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG
            assert mime == "image/png"
            # The route already resolved provider A. A separate transaction
            # now rebinds the same Telegram source row before extraction ends.
            with SessionLocal() as writer:
                # Do not deadlock the suite if extraction accidentally holds
                # a binding row lock while invoking this synchronous writer.
                # A Python/pytest timeout cannot cancel a blocked DB query.
                connection = writer.connection()
                connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                bound = writer.get(
                    models.ProviderSourceBinding, original["binding_id"]
                )
                assert bound is not None
                assert bound.provider_id == provider_a.id
                bound.provider_id = provider_b.id
                bound.feed_id = feed_b.id
                writer.commit()
            calls.append("rebound")
            return SimpleNamespace(
                raw_text=EUR_BUY, engine="offline-test",
                readable=True, confidence="HIGH", notes="",
            )

    before = db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED"
    ).count()
    monkeypatch.setattr(
        "app.routes.provider_sources.get_extractor", lambda: RebindingExtractor()
    )
    refused = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": "9392", **_source_claim(original)},
        files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert calls == ["rebound"], "Extraction never reached the in-flight rebind"
    assert refused.status_code == 409, refused.text
    db.expire_all()
    bound = db.get(models.ProviderSourceBinding, original["binding_id"])
    assert bound.provider_id == provider_b.id
    assert bound.feed_id == feed_b.id
    assert db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED"
    ).count() == before, "Rebound source produced an extraction audit"


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
