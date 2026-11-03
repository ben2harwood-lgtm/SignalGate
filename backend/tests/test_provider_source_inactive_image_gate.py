"""Offline regression: inactive tenant scope cannot invoke image extraction.

This tests source deactivation (status INACTIVE), not provider/feed pauses.
The paused-but-ACTIVE screenshot policy remains a separate unresolved HOLD.
No real model, Telegram, brokerage, provider credentials, or customer data.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from app import models
from app.routes import provider_sources

from .test_provider_sources import (
    EUR_BUY,
    _FAKE_PNG,
    _connect,
    _provider,
    _source_claim,
    _source_invite,
)


@pytest.mark.parametrize("inactive_scope_name", ("provider", "feed"))
def test_inactive_scope_refuses_image_before_extractor_and_audit(
    client, db, monkeypatch, inactive_scope_name
):
    """An inactive provider/feed refuses work, not just the final preview.

    Active-before/after controls prove the offline extractor and valid source
    claim actually work; refusal cannot pass vacuously from bad image/auth.
    """
    provider, feed, key = _provider(db, f"inactive-image-{inactive_scope_name}")
    connected = _connect(
        client, _source_invite(client, provider, feed, key), "9488"
    )
    assert connected.status_code == 200, connected.text
    claim = _source_claim(connected.json())
    calls = []

    class OfflineExtractor:
        engine = "offline-inactive-scope-test"

        def extract(self, image_bytes, *, mime):
            calls.append((image_bytes, mime))
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

    def extract_image():
        return client.post(
            "/provider-sources/telegram/extract",
            params={"telegram_user_id": "9488", **claim},
            files={"file": ("synthetic.png", io.BytesIO(_FAKE_PNG), "image/png")},
        )

    def audit_count():
        db.expire_all()
        return (
            db.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED")
            .count()
        )

    before = extract_image()
    assert before.status_code == 200, before.text
    assert len(calls) == 1
    assert calls[0] == (_FAKE_PNG, "image/png")
    assert audit_count() == 1

    inactive_scope = provider if inactive_scope_name == "provider" else feed
    inactive_scope.status = "INACTIVE"
    db.commit()

    refused = extract_image()
    assert refused.status_code == 403, refused.text
    assert len(calls) == 1, "Inactive source reached image extractor"
    assert audit_count() == 1, "Inactive source produced an extraction audit"

    inactive_scope.status = "ACTIVE"
    db.commit()
    restored = extract_image()
    assert restored.status_code == 200, restored.text
    assert len(calls) == 2
    assert audit_count() == 2

@pytest.mark.parametrize("inactive_scope_name", ("provider", "feed"))
def test_deactivation_mid_extraction_refuses_audit_postgresql(
    client, db, monkeypatch, inactive_scope_name
):
    """A committed scope deactivation during offline model I/O voids its preview.

    PostgreSQL is required for an independent writer transaction. This tests
    effective provider/feed status at the post-I/O read, not paused=True
    handling or transactional ordering of a subsequent status change.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from app.database import SessionLocal

    provider, feed, key = _provider(
        db, f"inactive-during-extraction-{inactive_scope_name}"
    )
    telegram_id = "9490" if inactive_scope_name == "provider" else "9491"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text
    snapshot = connected.json()
    calls = []
    target_model = (
        models.Provider if inactive_scope_name == "provider" else models.Feed
    )
    target_id = provider.id if inactive_scope_name == "provider" else feed.id

    class DeactivateDuringExtraction:
        engine = "offline-mid-deactivation"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG
            assert mime == "image/png"
            # The route has already resolved an ACTIVE source. An independent
            # transaction commits a status change while synthetic I/O runs.
            # Bound lock timeouts turn accidental lock retention into a
            # failure instead of an indefinitely blocked CI worker.
            with SessionLocal() as writer:
                conn = writer.connection()
                conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                target = writer.get(target_model, target_id)
                assert target is not None
                assert target.status == "ACTIVE"
                target.status = "INACTIVE"
                writer.commit()
            calls.append(inactive_scope_name)
            return SimpleNamespace(
                engine=self.engine,
                readable=True,
                confidence="HIGH",
                notes="",
                raw_text=EUR_BUY,
            )

    monkeypatch.setattr(
        provider_sources, "get_extractor", lambda: DeactivateDuringExtraction()
    )
    before = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED")
        .count()
    )
    refused = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": telegram_id, **_source_claim(snapshot)},
        files={"file": ("synthetic.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )

    assert calls == [inactive_scope_name], "Model I/O was never reached"
    assert refused.status_code == 409, refused.text
    db.expire_all()
    assert db.get(target_model, target_id).status == "INACTIVE"
    assert (
        db.get(models.ProviderSourceBinding, snapshot["binding_id"]).status
        == "ACTIVE"
    ), "Test must revoke effective scope, not the Telegram binding"
    assert (
        db.query(models.AuditLog)
        .filter(models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED")
        .count()
        == before
    ), "Deactivated source created a post-extraction audit receipt"
