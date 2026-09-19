"""Adversarial ingestion tests: replay, request size and content boundaries."""
from __future__ import annotations

from app import models
from app.database import SessionLocal

from .conftest import PROVIDER_HEADERS

VALID = "XAUUSD BUY SL 2343 TP1 2353"


def test_source_message_replay_returns_same_signal(client):
    payload = {
        "raw_text": VALID,
        "source": "TELEGRAM_PROVIDER",
        "source_message_id": "msg-42",
    }
    first = client.post("/signals/create", json=payload, headers=PROVIDER_HEADERS)
    second = client.post("/signals/create", json=payload, headers=PROVIDER_HEADERS)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    db = SessionLocal()
    try:
        assert db.query(models.Signal).count() == 1
    finally:
        db.close()


def test_raw_signal_request_has_size_limit(client):
    response = client.post(
        "/signals/create",
        json={"raw_text": "X" * 4001},
        headers=PROVIDER_HEADERS,
    )
    assert response.status_code == 422


def test_extractor_rejects_non_image_upload(client):
    response = client.post(
        "/signals/extract",
        files={"file": ("not-image.txt", b"hello", "text/plain")},
        headers=PROVIDER_HEADERS,
    )
    assert response.status_code == 415


def test_extractor_rejects_oversized_image(client):
    response = client.post(
        "/signals/extract",
        files={"file": ("huge.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
        headers=PROVIDER_HEADERS,
    )
    assert response.status_code == 413


def test_same_message_id_is_independent_across_source_namespaces(client):
    first = client.post(
        "/signals/create",
        json={
            "raw_text": VALID,
            "source": "TELEGRAM_CHAT:111",
            "source_message_id": "42",
        },
        headers=PROVIDER_HEADERS,
    )
    second = client.post(
        "/signals/create",
        json={
            "raw_text": VALID,
            "source": "TELEGRAM_CHAT:222",
            "source_message_id": "42",
        },
        headers=PROVIDER_HEADERS,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]

    db = SessionLocal()
    try:
        assert db.query(models.Signal).count() == 2
    finally:
        db.close()


def test_same_replay_key_with_different_content_is_conflict(client):
    key = {
        "source": "TELEGRAM_CHAT:111",
        "source_message_id": "42",
    }
    first = client.post(
        "/signals/create",
        json={"raw_text": VALID, **key},
        headers=PROVIDER_HEADERS,
    )
    conflict = client.post(
        "/signals/create",
        json={"raw_text": "XAUUSD BUY SL 2343 TP1 2360", **key},
        headers=PROVIDER_HEADERS,
    )
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "different signal content" in conflict.json()["detail"].lower()

    db = SessionLocal()
    try:
        assert db.query(models.Signal).count() == 1
        audit = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "SIGNAL_REPLAY_CONFLICT")
            .one()
        )
        assert audit.entity_id == first.json()["id"]
    finally:
        db.close()


def test_telegram_bot_submits_chat_scoped_replay_identity():
    from pathlib import Path

    bot_source = (
        Path(__file__).resolve().parents[2] / "telegram_bot" / "handlers.py"
    ).read_text(encoding="utf-8")
    assert '"source": f"TELEGRAM_CHAT:{chat_id}"' in bot_source
    assert '"source_message_id": message_id' in bot_source
