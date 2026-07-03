"""Tests for the screenshot -> signal extraction preview endpoint.

Uses the deterministic FakeExtractor (no API key, no real OCR) so the full
image -> extract -> parser path is exercised offline. The vision engine itself
is validated separately against a real chart image.
"""
from __future__ import annotations

import io
import os

from .conftest import ADMIN_HEADERS, PROVIDER_HEADERS, create_signal, register_user

# A tiny valid PNG header is enough; the fake extractor ignores image content.
_FAKE_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _post_image(client, headers=ADMIN_HEADERS):
    return client.post(
        "/signals/extract",
        headers=headers,
        files={"file": ("chart.png", io.BytesIO(_FAKE_PNG), "image/png")},
    )


def test_extract_valid_signal_preview(client):
    os.environ.pop("FAKE_EXTRACTOR_TEXT", None)  # use default valid BUY setup
    resp = _post_image(client)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["engine"] == "fake"
    assert data["parser_status"] == "VALID"
    assert data["symbol"] == "XAUUSD"
    assert data["direction"] == "BUY"
    assert data["initial_stop_loss"] == 2343.0
    assert data["tp1"] == 2353.0


def test_extract_preview_does_not_create_signal(client):
    """Extraction must PREVIEW only — no signal/command is created."""
    os.environ.pop("FAKE_EXTRACTOR_TEXT", None)
    before = client.get("/signals/recent", headers=ADMIN_HEADERS).json()
    _post_image(client)
    after = client.get("/signals/recent", headers=ADMIN_HEADERS).json()
    assert len(after) == len(before), "extract should not create a signal"


def test_extract_unsafe_signal_is_rejected_by_parser(client):
    """A misread/unsafe signal (BUY with SL above TP) must fail the parser."""
    os.environ["FAKE_EXTRACTOR_TEXT"] = "XAUUSD BUY SL 2360 TP1 2353"
    try:
        resp = _post_image(client)
        data = resp.json()
        assert data["parser_status"] == "REJECTED"
        assert data["parser_error"]
    finally:
        os.environ.pop("FAKE_EXTRACTOR_TEXT", None)


def test_extract_requires_admin(client):
    resp = _post_image(client, headers={"X-Admin-Id": "not-an-admin"})
    assert resp.status_code == 403


def test_signal_provider_can_extract_without_admin_access(client):
    os.environ.pop("FAKE_EXTRACTOR_TEXT", None)
    resp = _post_image(client, headers=PROVIDER_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["parser_status"] == "VALID"

    admin_resp = client.get("/admin/status", headers={"X-Admin-Id": "777"})
    assert admin_resp.status_code == 403


def test_signal_provider_can_create_confirmed_signal(client):
    resp = client.post(
        "/signals/create",
        headers=PROVIDER_HEADERS,
        json={"raw_text": "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["parser_status"] == "VALID"
    assert data["symbol"] == "XAUUSD"


def test_signal_provider_can_fetch_active_recipients(client):
    register_user(client, telegram_id="123")
    register_user(client, telegram_id="demo-tester-1")
    resp = client.get("/signals/recipients", headers=PROVIDER_HEADERS)
    assert resp.status_code == 200, resp.text
    recipients = resp.json()["recipients"]
    assert any(r["telegram_user_id"] == "123" for r in recipients)
    assert all(r["telegram_user_id"].lstrip("-").isdigit() for r in recipients)


def test_confirmed_text_creates_and_is_valid(client):
    """The text a provider confirms goes through the normal create path."""
    os.environ.pop("FAKE_EXTRACTOR_TEXT", None)
    preview = _post_image(client).json()
    # Simulate the bot's Confirm: create from the extracted text.
    created = create_signal(client, preview["extracted_text"])
    assert created["parser_status"] == "VALID"
    assert created["symbol"] == "XAUUSD"
