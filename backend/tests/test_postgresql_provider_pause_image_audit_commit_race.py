"""PostgreSQL release HOLD: pause must serialize with screenshot-audit commit.

Offline, synthetic-only test of the narrow interval after extraction has
re-read the Telegram binding but before its audit transaction commits.
Provider/feed pause is independent of binding reauthorization; a binding-only
FOR UPDATE lock cannot establish pause ordering.

This is intentionally a strict RED-before XFAIL. Green CI with XFAIL does not
mean the pause protection has been implemented or externally accepted.
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app import crud, models
from app.database import SessionLocal
from app.routes import provider_sources

from .test_provider_sources import (
    EUR_BUY,
    _FAKE_PNG,
    _connect,
    _provider,
    _source_claim,
    _source_invite,
)


class _PauseOvertookImageAudit(AssertionError):
    """An already committed pause was overtaken by a screenshot audit commit."""


@pytest.mark.parametrize("scope_name", ("provider", "feed"))
@pytest.mark.xfail(
    strict=True,
    raises=_PauseOvertookImageAudit,
    reason=(
        "RELEASE HOLD: image audit does not serialize with a provider/feed "
        "pause committed after the last source re-read but before audit commit"
    ),
)
def test_committed_pause_cannot_be_overtaken_by_image_audit_postgresql(
    client, db, monkeypatch, scope_name
):
    """RED-before: test the gap AFTER the route's final source-status lookup.

    Block the HTTP worker on the exact extraction-audit call. A second real
    PostgreSQL transaction attempts to pause the ACTIVE provider/feed. A
    correct transaction-scoped provider/feed lock keeps that UPDATE waiting
    until the audit finishes. Without it the pause commits first and the
    old screenshot still obtains a preview plus an audit, which is rejected.

    An actual competing SQL UPDATE is observed and all waits are bounded.
    No broker, Telegram, model service, external user, or paid API is used.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    provider, feed, key = _provider(
        db, f"image-audit-commit-race-{scope_name}"
    )
    telegram_id = "9511" if scope_name == "provider" else "9512"
    connected = _connect(
        client,
        _source_invite(client, provider, feed, key),
        telegram_id,
    )
    assert connected.status_code == 200, connected.text
    claim = _source_claim(connected.json())
    model = models.Provider if scope_name == "provider" else models.Feed
    target_id = provider.id if scope_name == "provider" else feed.id

    audit_reached = Event()
    release_audit = Event()
    pause_update_attempted = Event()
    pause_committed = Event()
    extractor_called = Event()

    class OfflineExtractor:
        engine = "offline-image-audit-order"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG
            assert mime == "image/png"
            extractor_called.set()
            return SimpleNamespace(
                engine=self.engine,
                readable=True,
                confidence="HIGH",
                notes="",
                raw_text=EUR_BUY,
            )

    monkeypatch.setattr(
        provider_sources, "get_extractor", lambda: OfflineExtractor()
    )
    original_add_audit = crud.add_audit

    def block_before_extraction_audit(session, event_type, entity_type, entity_id, payload):
        if event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED":
            audit_reached.set()
            assert release_audit.wait(timeout=18), (
                "Image-audit transaction was never released by the test"
            )
        return original_add_audit(
            session, event_type, entity_type, entity_id, payload
        )

    monkeypatch.setattr(crud, "add_audit", block_before_extraction_audit)

    def image_audit_count():
        with SessionLocal() as reader:
            return (
                reader.query(models.AuditLog)
                .filter(
                    models.AuditLog.event_type
                    == "PROVIDER_SOURCE_IMAGE_EXTRACTED",
                    models.AuditLog.entity_id == claim["expected_binding_id"],
                )
                .count()
            )

    before_count = image_audit_count()

    def request_preview():
        return client.post(
            "/provider-sources/telegram/extract",
            params={"telegram_user_id": telegram_id, **claim},
            files={
                "file": (
                    "synthetic.png",
                    io.BytesIO(_FAKE_PNG),
                    "image/png",
                ),
            },
        )

    def commit_pause():
        with SessionLocal() as writer:
            conn = writer.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            def observe_update(_conn, _cursor, statement, _params, _ctx, _many):
                if statement.lstrip().lower().startswith(
                    f"update {model.__tablename__} set"
                ):
                    pause_update_attempted.set()

            event.listen(conn, "before_cursor_execute", observe_update)
            target = writer.get(model, target_id)
            assert target is not None
            assert target.status == "ACTIVE"
            assert target.paused is False
            target.paused = True
            writer.commit()
            # Capture the commit order before the first thread is released.
            committed_first = not release_audit.is_set()
            pause_committed.set()
            return committed_first

    with ThreadPoolExecutor(max_workers=2) as workers:
        preview_future = workers.submit(request_preview)
        try:
            assert audit_reached.wait(timeout=8), (
                "Preview never reached the post-lookup audit barrier"
            )
            assert extractor_called.is_set(), (
                "Synthetic extractor was not called before the barrier"
            )
            pause_future = workers.submit(commit_pause)
            assert pause_update_attempted.wait(timeout=8), (
                "Competing pause never attempted its PostgreSQL UPDATE"
            )
            # If provider/feed locks are missing, pause commits here.
            # With correct locks it must wait; then the already earlier
            # image-audit transaction may complete before the later pause.
            pause_committed.wait(timeout=1.5)
        finally:
            release_audit.set()
        response = preview_future.result(timeout=22)
        pause_overtook = pause_future.result(timeout=22)

    with SessionLocal() as check:
        target = check.get(model, target_id)
        assert target is not None
        assert target.status == "ACTIVE" and target.paused is True
        binding = check.get(
            models.ProviderSourceBinding, claim["expected_binding_id"]
        )
        assert binding is not None and binding.status == "ACTIVE"
    after_count = image_audit_count()

    assert response.status_code in (200, 409), response.text
    if pause_overtook:
        if response.status_code != 409 or after_count != before_count:
            raise _PauseOvertookImageAudit(
                f"{scope_name} pause committed before image audit release, "
                f"but HTTP={response.status_code} and audit count changed "
                f"{before_count}->{after_count}"
            )
    else:
        assert response.status_code == 200, response.text
        assert after_count == before_count + 1, (
            "Audit was not committed before the later provider/feed pause"
        )


@pytest.mark.parametrize(
    "independent_scope",
    (
        "sibling_feed",
        "same_org_provider",
        "same_org_feed",
        "cross_org_provider",
        "cross_org_feed",
    ),
)
def test_independent_pause_commits_while_image_audit_is_held_postgresql(
    client, db, monkeypatch, independent_scope
):
    """A held screenshot audit cannot block unrelated providers or feeds.

    The bound feed's image-audit transaction is held at its pre-commit gate,
    while a different feed of the same provider, another provider in the SAME
    organisation, or a provider in a different organisation pauses in a real
    second PostgreSQL transaction. These are passing isolation controls, not
    repairs of the two same-scope strict XFAILs. Offline synthetic data only.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    provider, feed, key = _provider(db, f"image-audit-owner-{independent_scope}")
    provider_id, feed_id = provider.id, feed.id
    if independent_scope == "sibling_feed":
        sibling = crud.create_feed(
            db, provider, "Unrelated sibling feed", "image-audit-sibling"
        )
        db.commit()
        target_model, target_id = models.Feed, sibling.id
        assert sibling.provider_id == provider_id
    elif independent_scope.startswith("same_org_"):
        other = crud.create_provider(
            db,
            provider.organization_id,
            f"Independent image provider {independent_scope}",
            f"image-audit-{independent_scope}",
        )
        other_feed = crud.create_feed(
            db, other, "Independent image feed",
            f"image-audit-feed-{independent_scope}",
        )
        db.commit()
        target_model = (
            models.Provider if independent_scope == "same_org_provider"
            else models.Feed
        )
        target_id = (
            other.id if target_model is models.Provider else other_feed.id
        )
        assert other.id != provider_id
        assert other.organization_id == provider.organization_id
        assert other_feed.provider_id == other.id
    else:
        other, other_feed, _ = _provider(
            db, f"image-audit-other-{independent_scope}"
        )
        target_model = (
            models.Provider if independent_scope == "cross_org_provider"
            else models.Feed
        )
        target_id = (
            other.id if target_model is models.Provider else other_feed.id
        )
        assert other.organization_id != provider.organization_id
    assert target_id != (
        provider_id if target_model is models.Provider else feed_id
    )

    telegram_id = "9513"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text
    claim = _source_claim(connected.json())

    audit_reached = Event()
    release_audit = Event()
    extractor_called = Event()
    original_add_audit = crud.add_audit

    class OfflineExtractor:
        engine = "offline-sibling-feed-pause"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG and mime == "image/png"
            extractor_called.set()
            return SimpleNamespace(
                engine=self.engine,
                readable=True,
                confidence="HIGH",
                notes="",
                raw_text=EUR_BUY,
            )

    monkeypatch.setattr(
        provider_sources, "get_extractor", lambda: OfflineExtractor()
    )

    def hold_image_audit(session, event_type, entity_type, entity_id, payload):
        if event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED":
            audit_reached.set()
            assert release_audit.wait(timeout=18), (
                "Synthetic image-audit transaction was not released"
            )
        return original_add_audit(
            session, event_type, entity_type, entity_id, payload
        )

    monkeypatch.setattr(crud, "add_audit", hold_image_audit)

    def preview_bound_feed():
        return client.post(
            "/provider-sources/telegram/extract",
            params={"telegram_user_id": telegram_id, **claim},
            files={
                "file": (
                    "synthetic.png", io.BytesIO(_FAKE_PNG), "image/png"
                ),
            },
        )

    def pause_independent_scope():
        with SessionLocal() as writer:
            connection = writer.connection()
            connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            unrelated = writer.get(target_model, target_id)
            assert unrelated is not None
            assert unrelated.status == "ACTIVE" and unrelated.paused is False
            if independent_scope == "sibling_feed":
                assert unrelated.provider_id == provider_id
            unrelated.paused = True
            writer.commit()
            return not release_audit.is_set()

    with SessionLocal() as check:
        before_audits = (
            check.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED",
                models.AuditLog.entity_id == claim["expected_binding_id"],
            )
            .count()
        )
        before_executions = tuple(
            check.query(model).count()
            for model in (models.Signal, models.Command, models.Execution)
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        image_future = workers.submit(preview_bound_feed)
        try:
            assert audit_reached.wait(timeout=8), (
                "Bound feed did not reach its pre-commit screenshot audit gate"
            )
            assert extractor_called.is_set(), "Offline extractor was not called"
            pause_future = workers.submit(pause_independent_scope)
            assert pause_future.result(timeout=9) is True, (
                f"A held image audit blocked {independent_scope} pause"
            )
        finally:
            release_audit.set()
        image_response = image_future.result(timeout=22)

    assert image_response.status_code == 200, image_response.text
    with SessionLocal() as check:
        bound_provider = check.get(models.Provider, provider_id)
        bound_feed = check.get(models.Feed, feed_id)
        paused_target = check.get(target_model, target_id)
        assert bound_provider is not None and bound_provider.paused is False
        assert bound_feed is not None and bound_feed.paused is False
        assert paused_target is not None and paused_target.paused is True
        if independent_scope == "sibling_feed":
            assert paused_target.provider_id == provider_id
        else:
            other_provider = (
                paused_target if target_model is models.Provider
                else check.get(models.Provider, paused_target.provider_id)
            )
            assert other_provider is not None
            assert other_provider.id != provider_id
            if independent_scope.startswith("same_org_"):
                assert other_provider.organization_id == bound_provider.organization_id
            else:
                assert other_provider.organization_id != bound_provider.organization_id
        audit_rows = (
            check.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED",
                models.AuditLog.entity_id == claim["expected_binding_id"],
            )
            .all()
        )
        assert len(audit_rows) == before_audits + 1, (
            "Exactly one bound-source image audit must commit"
        )
        assert audit_rows[-1].entity_type == "provider_source_binding"
        assert f'"provider_id": "{provider_id}"' in (
            audit_rows[-1].payload_json or ""
        )
        assert f'"feed_id": "{feed_id}"' in (
            audit_rows[-1].payload_json or ""
        )
        assert tuple(
            check.query(model).count()
            for model in (models.Signal, models.Command, models.Execution)
        ) == before_executions, "A preview must never create trading state"


@pytest.mark.parametrize("paused_scope", ("provider", "feed"))
def test_pause_during_offline_image_io_blocks_later_signal_postgresql(
    client, db, monkeypatch, paused_scope
):
    """A provider/feed pause must commit during model I/O, without trading state.

    This deliberately does not decide whether an already-paused source can
    receive a *preview*: that policy requires the runtime source owner's
    decision. The later signal POST must always fail closed. Synthetic only.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    provider, feed, key = _provider(db, f"image-io-pause-{paused_scope}")
    telegram_id = "9524" if paused_scope == "provider" else "9525"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text
    claim = _source_claim(connected.json())
    model = models.Provider if paused_scope == "provider" else models.Feed
    target_id = provider.id if paused_scope == "provider" else feed.id
    pause_commits = []

    with SessionLocal() as check:
        before_trading = tuple(
            check.query(m).count()
            for m in (models.Signal, models.Command, models.Execution)
        )
        before_created_audits = (
            check.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "SIGNAL_CREATED")
            .count()
        )

    class OfflinePauseExtractor:
        engine = "offline-image-io-pause"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG and mime == "image/png"
            with SessionLocal() as writer:
                conn = writer.connection()
                # A repair must never lock provider/feed rows over model I/O.
                conn.exec_driver_sql("SET LOCAL lock_timeout = '4s'")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '6s'")
                target = writer.get(model, target_id)
                assert target is not None
                assert target.status == "ACTIVE" and target.paused is False
                target.paused = True
                writer.commit()
            pause_commits.append(paused_scope)
            return SimpleNamespace(
                engine=self.engine, readable=True, confidence="HIGH",
                notes="", raw_text=EUR_BUY,
            )

    monkeypatch.setattr(
        provider_sources, "get_extractor", lambda: OfflinePauseExtractor()
    )
    preview = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": telegram_id, **claim},
        files={"file": ("synthetic.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert pause_commits == [paused_scope], (
        "Provider/feed pause did not commit during extractor I/O"
    )
    # Preview refusal policy is separately HELD; never treat 200 as approval.
    assert preview.status_code in (200, 403, 409), preview.text

    rejected = client.post(
        "/provider-sources/telegram/signals",
        json={
            "telegram_user_id": telegram_id,
            "raw_text": EUR_BUY,
            "source_message_id": f"{telegram_id}:after-pause",
            **claim,
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "paused" in rejected.json()["detail"].lower()
    with SessionLocal() as check:
        target = check.get(model, target_id)
        binding = check.get(
            models.ProviderSourceBinding, claim["expected_binding_id"]
        )
        assert target is not None
        assert target.status == "ACTIVE" and target.paused is True
        assert binding is not None and binding.status == "ACTIVE"
        assert binding.provider_id == provider.id and binding.feed_id == feed.id
        assert tuple(
            check.query(m).count()
            for m in (models.Signal, models.Command, models.Execution)
        ) == before_trading, "Paused source created trading state"
        assert (
            check.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "SIGNAL_CREATED")
            .count()
        ) == before_created_audits


def test_feed_policy_commit_during_image_io_controls_preview_postgresql(
    client, db, monkeypatch
):
    """Use the committed tenant feed allowlist, not the pre-I/O snapshot.

    A policy change during synthetic image extraction must commit without a
    database row lock being held across model I/O. The eventual preview must
    be REJECTED under the newly restrictive feed policy, with only metadata
    audited and no signal or execution written. No external service is used.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    provider, feed, key = _provider(db, "image-policy-update-during-io")
    crud.update_feed_policy(db, feed, {"allowed_symbols": ["EURUSD"]})
    db.commit()
    feed_id = feed.id
    telegram_id = "9536"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text
    claim = _source_claim(connected.json())
    policy_commit_observed = []

    with SessionLocal() as check:
        before_audits = (
            check.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED",
                models.AuditLog.entity_id == claim["expected_binding_id"],
            )
            .count()
        )
        before_trading = tuple(
            check.query(model).count()
            for model in (models.Signal, models.Command, models.Execution)
        )

    class OfflinePolicyChangeExtractor:
        engine = "offline-policy-change-during-io"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG and mime == "image/png"
            with SessionLocal() as writer:
                conn = writer.connection()
                conn.exec_driver_sql("SET LOCAL lock_timeout = '4s'")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '6s'")
                current_feed = writer.get(models.Feed, feed_id)
                assert current_feed is not None
                assert current_feed.status == "ACTIVE"
                assert current_feed.paused is False
                assert crud.feed_allowed_symbols(current_feed) == {"EURUSD"}
                crud.update_feed_policy(
                    writer, current_feed, {"allowed_symbols": ["XAUUSD"]}
                )
                writer.commit()
            policy_commit_observed.append(feed_id)
            return SimpleNamespace(
                engine=self.engine,
                readable=True,
                confidence="HIGH",
                notes="",
                raw_text=EUR_BUY,
            )

    monkeypatch.setattr(
        provider_sources, "get_extractor",
        lambda: OfflinePolicyChangeExtractor(),
    )
    response = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": telegram_id, **claim},
        files={"file": ("synthetic.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert policy_commit_observed == [feed_id], (
        "The independent feed policy update did not commit during extraction"
    )
    assert response.status_code == 200, response.text
    assert response.json()["symbol"] == "EURUSD"
    assert response.json()["parser_status"] == "REJECTED", (
        "Preview accepted a symbol after its feed policy was revoked"
    )
    assert "not enabled" in (response.json()["parser_error"] or "").lower()

    with SessionLocal() as check:
        committed_feed = check.get(models.Feed, feed_id)
        assert committed_feed is not None
        assert crud.feed_allowed_symbols(committed_feed) == {"XAUUSD"}
        audit_rows = (
            check.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED",
                models.AuditLog.entity_id == claim["expected_binding_id"],
            )
            .all()
        )
        assert len(audit_rows) == before_audits + 1
        assert '"parser_status": "REJECTED"' in (
            audit_rows[-1].payload_json or ""
        )
        assert tuple(
            check.query(model).count()
            for model in (models.Signal, models.Command, models.Execution)
        ) == before_trading, "Image preview wrote trading or execution state"

