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
