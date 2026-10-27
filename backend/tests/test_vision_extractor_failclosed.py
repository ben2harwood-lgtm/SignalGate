"""Offline hostile vision-response tests. No API key, network or broker access."""
from __future__ import annotations

import json

import httpx
import pytest

from app.vision_extractor import ClaudeExtractor, _parse_model_json


TRADE = "XAUUSD BUY ENTRY 2348 SL 2343 TP1 2353 TP2 2358 TP3 2363"
GOOD_MODEL = {
    "readable": True,
    "signal_text": TRADE,
    "confidence": "HIGH",
    "notes": "Synthetic image.",
}


def _must_refuse(result):
    assert result.readable is False
    assert result.raw_text == ""
    assert result.confidence == "LOW"
    assert isinstance(result.notes, str)
    assert result.notes


@pytest.mark.parametrize(
    "changes",
    [
        {"readable": "false"},
        {"readable": 1},
        {"readable": None},
        {"signal_text": [TRADE]},
        {"signal_text": {"text": TRADE}},
        {"signal_text": None},
        {"confidence": 9},
        {"confidence": "CERTAIN"},
        {"notes": {"unexpected": "synthetic-secret"}},
        {"notes": "x" * 2049},
        {"signal_text": TRADE + "\nSELL XAUUSD"},
        {"signal_text": TRADE + "\x00"},
        {"signal_text": "x" * 2049},
    ],
)
def test_untrusted_model_field_shapes_fail_closed(changes):
    payload = {**GOOD_MODEL, **changes}
    result = _parse_model_json(json.dumps(payload), engine="claude")
    _must_refuse(result)
    assert "synthetic-secret" not in (result.notes or "")


def test_unreadable_flag_discards_otherwise_valid_signal_text():
    result = _parse_model_json(
        json.dumps({**GOOD_MODEL, "readable": False}), engine="claude",
    )
    _must_refuse(result)


def test_valid_model_text_and_embedded_json_remain_readable():
    for text in (json.dumps(GOOD_MODEL), "prefix " + json.dumps(GOOD_MODEL) + " suffix"):
        result = _parse_model_json(text, engine="claude")
        assert result.readable is True
        assert result.raw_text == TRADE
        assert result.confidence == "HIGH"


def _mock_http_client(monkeypatch, responder):
    # httpx.MockTransport prevents all outbound traffic, even on exceptions.
    actual_client = httpx.Client
    transport = httpx.MockTransport(responder)

    def replacement(*args, **kwargs):
        return actual_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", replacement)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-synthetic-key-not-a-secret")


@pytest.mark.parametrize(
    "body",
    [
        [42],
        {"content": None},
        {"content": {}},
        {"content": [False]},
        {"content": [{"type": "text", "text": [TRADE]}]},
        {"content": [{"type": "text", "text": None}]},
        {"content": [{"type": "text", "text": {"value": TRADE}}]},
        {"content": []},
    ],
)
def test_malformed_vision_service_envelopes_fail_closed(monkeypatch, body):
    _mock_http_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder", mime="image/png"))


def test_valid_vision_service_envelope_is_parsed_offline(monkeypatch):
    envelope = {
        "content": [
            {"type": "text", "text": json.dumps(GOOD_MODEL)},
        ],
    }
    _mock_http_client(
        monkeypatch, lambda request: httpx.Response(200, json=envelope),
    )
    result = ClaudeExtractor().extract(b"offline-placeholder")
    assert result.readable is True
    assert result.raw_text == TRADE
    assert result.confidence == "HIGH"


def test_transport_exception_cannot_echo_sensitive_details(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("synthetic-secret-token-in-transport", request=request)

    _mock_http_client(monkeypatch, refuse)
    result = ClaudeExtractor().extract(b"offline-placeholder")
    _must_refuse(result)
    assert "synthetic-secret-token-in-transport" not in result.notes


def test_http_error_body_does_not_appear_in_preview(monkeypatch):
    _mock_http_client(
        monkeypatch,
        lambda request: httpx.Response(
            500, json={"error": {"message": "synthetic-secret-token-in-body"}},
        ),
    )
    result = ClaudeExtractor().extract(b"offline-placeholder")
    _must_refuse(result)
    assert "synthetic-secret-token-in-body" not in result.notes


@pytest.mark.parametrize(
    "unsafe",
    [
        "\\u2028",  # Unicode line separator (renders as another line).
        "\\u2029",  # Unicode paragraph separator.
        "\\u200b",  # Zero-width space.
        "\\u202e",  # Right-to-left override.
        "\\u2066",  # Left-to-right isolate.
        "\\x7f",    # ASCII delete/control (not caught by ord < 32).
        "\\n",      # Actual newline, even after trim.
        "\\t",      # Tab, even after trim.
    ],
)
def test_vision_signal_text_refuses_invisible_or_multiline_controls(unsafe):
    candidate = TRADE.replace(" TP1", unsafe + " TP1", 1)
    _must_refuse(_parse_model_json(
        json.dumps({**GOOD_MODEL, "signal_text": candidate}), engine="claude",
    ))
    # Trimming must not turn a hidden boundary character into a valid preview.
    _must_refuse(_parse_model_json(
        json.dumps({**GOOD_MODEL, "signal_text": TRADE + unsafe}), engine="claude",
    ))


def test_vision_model_json_is_bounded_before_parsing():
    # An untrusted service may violate the upstream 400-token output setting.
    # Neither an oversized plain response nor deeply nested JSON is a signal.
    for text in ("x" * 8193, "[" * 5000 + "]" * 5000):
        _must_refuse(_parse_model_json(text, engine="claude"))


def test_vision_signal_allows_plain_ascii_surrounding_spaces():
    result = _parse_model_json(
        json.dumps({**GOOD_MODEL, "signal_text": "  " + TRADE + "  "}),
        engine="claude",
    )
    assert result.readable is True
    assert result.raw_text == TRADE
