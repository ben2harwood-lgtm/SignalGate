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


class _PausedDuringExtractionAccess(AssertionError):
    """Known release-blocking screenshot pause race during offline model I/O."""


@pytest.mark.parametrize("paused_scope_name", ("provider", "feed"))
@pytest.mark.xfail(
    strict=True,
    raises=_PausedDuringExtractionAccess,
    reason=(
        "RELEASE HOLD: a committed provider/feed pause during screenshot "
        "extraction is not rechecked before preview/audit; requires "
        "source-owner repair and PostgreSQL transaction-lock review"
    ),
)
def test_pause_mid_extraction_refuses_preview_postgresql(
    client, db, monkeypatch, paused_scope_name
):
    """RED-before witness: pause commits in independent PG session during I/O.

    The synthetic extractor is the synchronization point. The source is
    ACTIVE and unpaused when extraction begins; a second transaction then
    commits paused=True while the first request is in progress. Neither a
    post-pause preview nor an extraction audit is acceptable. Strict XFAIL
    records the known defect, not acceptance of the pause policy.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from app.database import SessionLocal

    provider, feed, key = _provider(
        db, f"paused-during-image-{paused_scope_name}"
    )
    telegram_id = "9503" if paused_scope_name == "provider" else "9504"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text
    snapshot = connected.json()
    target_model = (
        models.Provider if paused_scope_name == "provider" else models.Feed
    )
    target_id = provider.id if paused_scope_name == "provider" else feed.id
    calls = []

    class PauseDuringExtraction:
        engine = "offline-mid-pause-hold"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG
            assert mime == "image/png"
            calls.append(paused_scope_name)
            with SessionLocal() as writer:
                conn = writer.connection()
                conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                target = writer.get(target_model, target_id)
                assert target is not None
                assert target.status == "ACTIVE"
                assert target.paused is False
                target.paused = True
                writer.commit()
            return SimpleNamespace(
                engine=self.engine,
                readable=True,
                confidence="HIGH",
                notes="",
                raw_text=EUR_BUY,
            )

    monkeypatch.setattr(
        provider_sources, "get_extractor", lambda: PauseDuringExtraction()
    )
    audit_query = db.query(models.AuditLog).filter(
        models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED"
    )
    before = audit_query.count()
    response = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": telegram_id, **_source_claim(snapshot)},
        files={"file": ("synthetic.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )

    assert calls == [paused_scope_name], "The offline model path was not reached"
    db.expire_all()
    authoritative = db.get(target_model, target_id)
    assert authoritative is not None
    assert authoritative.status == "ACTIVE"
    assert authoritative.paused is True, "Independent pause did not commit"
    assert (
        db.get(models.ProviderSourceBinding, snapshot["binding_id"]).status
        == "ACTIVE"
    ), "This scenario pauses scope without deactivating its binding"
    after = audit_query.count()
    if response.status_code != 409 or after != before:
        raise _PausedDuringExtractionAccess(
            "Paused scope yielded a post-I/O preview or audit: "
            f"scope={paused_scope_name}, HTTP={response.status_code}, "
            f"new_audits={after - before}"
        )


@pytest.mark.parametrize(
    ("raw_text", "expected_status"),
    (
        (EUR_BUY, "VALID"),
        ("SYNTHETIC_PRIVATE_UNPARSEABLE_SIGNAL_7C91", "REJECTED"),
    ),
)
def test_image_extraction_audit_omits_raw_model_content(
    client, db, monkeypatch, raw_text, expected_status
):
    """Only allowlisted extraction metadata belongs in the durable audit log.

    Both a valid preview and a rejected model output may contain sensitive
    source material. They may be returned to the requesting demo bot, but must
    not be copied into persistent extraction-audit payloads. All inputs are
    synthetic and extraction is entirely in-process; no provider/model/broker.
    """
    provider, feed, key = _provider(
        db, f"extraction-audit-privacy-{expected_status.lower()}"
    )
    telegram_id = "9492" if expected_status == "VALID" else "9493"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text
    private_notes = "SYNTHETIC_PRIVATE_IMAGE_NOTES_9F30"
    calls = []

    class PrivateOfflineExtractor:
        engine = "offline-audit-privacy"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG
            assert mime == "image/png"
            calls.append(1)
            return SimpleNamespace(
                engine=self.engine,
                readable=True,
                confidence="HIGH",
                notes=private_notes,
                raw_text=raw_text,
            )

    monkeypatch.setattr(
        provider_sources, "get_extractor", lambda: PrivateOfflineExtractor()
    )
    # A screenshot preview, VALID or REJECTED, is not a human-authorised
    # signal submission and must never generate downstream execution state.
    tracked_models = (models.Signal, models.Command, models.Execution)
    before_trades = tuple(db.query(model).count() for model in tracked_models)
    response = client.post(
        "/provider-sources/telegram/extract",
        params={"telegram_user_id": telegram_id, **_source_claim(connected.json())},
        files={"file": ("synthetic.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert calls == [1], "Test did not invoke the synthetic extractor"
    assert response.json()["extracted_text"] == raw_text
    assert response.json()["notes"] == private_notes
    assert response.json()["parser_status"] == expected_status

    db.expire_all()
    after_trades = tuple(db.query(model).count() for model in tracked_models)
    assert after_trades == before_trades, (
        "Screenshot preview created a signal/command/execution without "
        f"human authorisation: {before_trades} -> {after_trades}"
    )
    rows = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED",
            models.AuditLog.entity_id == connected.json()["binding_id"],
        )
        .all()
    )
    assert len(rows) == 1, "Exactly one metadata-only extraction audit is expected"
    payload = rows[0].payload_json or ""
    assert "offline-audit-privacy" in payload, "Audit control was not exercised"
    assert raw_text not in payload, "Model text leaked into the durable audit"
    assert private_notes not in payload, "Model notes leaked into the durable audit"
    assert "raw_text" not in payload and "extracted_text" not in payload
    assert key not in payload, "Synthetic provider credential leaked into audit"



@pytest.mark.parametrize(
    ("content_type", "payload", "expected_status"),
    (
        ("application/octet-stream", _FAKE_PNG, 415),
        (
            "image/png",
            b"x" * (provider_sources.MAX_SIGNAL_IMAGE_BYTES + 1),
            413,
        ),
    ),
)
def test_invalid_screenshot_upload_rejected_before_extractor(
    client, db, monkeypatch, content_type, payload, expected_status
):
    """Reject invalid image metadata/size before model I/O or a durable record.

    Exact-size boundaries are derived from the route constant; all bytes,
    identities and source claims are synthetic. No network or broker is used.
    """
    provider, feed, key = _provider(
        db, f"invalid-screenshot-{expected_status}"
    )
    telegram_id = f"949{expected_status}"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text

    def forbidden_extractor():
        raise AssertionError("Invalid upload reached model extractor")

    monkeypatch.setattr(
        provider_sources, "get_extractor", forbidden_extractor
    )
    tracked_models = (
        models.AuditLog,
        models.Signal,
        models.Command,
        models.Execution,
    )
    before = tuple(db.query(model).count() for model in tracked_models)

    response = client.post(
        "/provider-sources/telegram/extract",
        params={
            "telegram_user_id": telegram_id,
            **_source_claim(connected.json()),
        },
        files={
            "file": ("synthetic-image.bin", io.BytesIO(payload), content_type)
        },
    )

    assert response.status_code == expected_status, response.text
    db.expire_all()
    after = tuple(db.query(model).count() for model in tracked_models)
    assert after == before, (
        "Rejected screenshot created durable audit or execution state: "
        f"{before} -> {after}"
    )


class _PausedScreenshotAccess(AssertionError):
    """Known release-blocking paused-but-ACTIVE screenshot policy gap."""


@pytest.mark.parametrize("paused_scope_name", ("provider", "feed"))
@pytest.mark.xfail(
    strict=True,
    raises=_PausedScreenshotAccess,
    reason=(
        "RELEASE HOLD: paused-but-ACTIVE provider/feed image preview "
        "is not yet refused before model I/O; policy/locking fix requires "
        "source-owner clearance, PostgreSQL tests, and independent review"
    ),
)
def test_paused_but_active_scope_extraction_hold(
    client, db, monkeypatch, paused_scope_name
):
    """Executable RED-before witness, not an accepted safety fix.

    A pause is distinct from changing status to INACTIVE: prior successful
    deactivation tests do not cover it. The strict expected failure allows
    CI to stay usable while the hold is owned; an eventual unexpected pass
    must break CI until this marker is removed after independent review.
    The test asserts a valid active positive control first, and only the
    precisely identified paused-access violation is classified as XFAIL.
    """
    provider, feed, key = _provider(
        db, f"paused-image-hold-{paused_scope_name}"
    )
    telegram_id = "9501" if paused_scope_name == "provider" else "9502"
    connected = _connect(
        client, _source_invite(client, provider, feed, key), telegram_id
    )
    assert connected.status_code == 200, connected.text
    claim = _source_claim(connected.json())
    calls = []

    class OfflineExtractor:
        engine = "offline-paused-image-hold"

        def extract(self, image_bytes, *, mime):
            assert image_bytes == _FAKE_PNG
            assert mime == "image/png"
            calls.append(1)
            return SimpleNamespace(
                engine=self.engine,
                readable=True,
                confidence="HIGH",
                notes="",
                raw_text=EUR_BUY,
            )

    monkeypatch.setattr(provider_sources, "get_extractor", OfflineExtractor)

    def preview():
        return client.post(
            "/provider-sources/telegram/extract",
            params={"telegram_user_id": telegram_id, **claim},
            files={"file": ("synthetic.png", io.BytesIO(_FAKE_PNG), "image/png")},
        )

    def audit_count():
        db.expire_all()
        return (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "PROVIDER_SOURCE_IMAGE_EXTRACTED"
            )
            .count()
        )

    active = preview()
    assert active.status_code == 200, active.text
    assert calls == [1], "Active positive control did not invoke extractor"
    assert audit_count() == 1

    scope = provider if paused_scope_name == "provider" else feed
    scope.paused = True
    db.commit()
    db.expire_all()
    assert db.get(type(scope), scope.id).status == "ACTIVE"
    assert db.get(type(scope), scope.id).paused is True
    before_audits = audit_count()

    paused_response = preview()
    after_audits = audit_count()
    if (
        paused_response.status_code != 403
        or calls != [1]
        or after_audits != before_audits
    ):
        raise _PausedScreenshotAccess(
            "Paused-but-ACTIVE scope still allowed screenshot work: "
            f"scope={paused_scope_name}, HTTP={paused_response.status_code}, "
            f"extractor_calls={len(calls)}, "
            f"new_audits={after_audits - before_audits}"
        )
