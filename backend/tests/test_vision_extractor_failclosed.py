"""Offline hostile vision-response tests. No API key, network or broker access."""
from __future__ import annotations

import gzip
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

@pytest.mark.parametrize("field", ["readable", "signal_text", "confidence", "notes"])
@pytest.mark.parametrize("embedded", [False, True])
def test_duplicate_model_json_keys_fail_closed_even_if_last_value_is_valid(field, embedded):
    # The first value contradicts the valid second value. json.loads without
    # duplicate detection silently takes the last value and accepts a preview.
    text = ("{" + json.dumps(field) + ':"spoofed",'
            + json.dumps(GOOD_MODEL)[1:])
    if embedded:
        text = "model response: " + text + " end"
    _must_refuse(_parse_model_json(text, engine="claude"))


def test_unicode_escaped_duplicate_model_json_key_is_refused():
    # JSON escape sequences decode to the same field name and must not bypass
    # duplicate detection during the embedded-object recovery path.
    text = r'{"\u0072eadable":false,' + json.dumps(GOOD_MODEL)[1:]
    _must_refuse(_parse_model_json("prefix " + text + " suffix", engine="claude"))


def _mock_http_client(monkeypatch, responder):
    # httpx.MockTransport prevents all outbound traffic, even on exceptions.
    actual_client = httpx.Client

    def streamed_responder(request):
        response = responder(request)
        # Response(..., json=...) eagerly buffers synthetic bodies, unlike a
        # network response inside Client.stream(). Re-expose test fixtures as
        # truly streamed bytes so production iter_raw() exercises the JSON
        # parser rather than failing with httpx.StreamConsumed. Preserve
        # explicitly streamed hostile-gzip responses untouched.
        if response.is_stream_consumed:
            response = httpx.Response(
                response.status_code,
                headers=response.headers,
                stream=httpx.ByteStream(response.content),
                request=request,
            )
        return response

    transport = httpx.MockTransport(streamed_responder)

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

def test_http_duplicate_model_keys_never_produce_preview(monkeypatch):
    model = '{"readable":false,' + json.dumps(GOOD_MODEL)[1:]
    envelope = {"content": [{"type": "text", "text": model}]}
    _mock_http_client(
        monkeypatch, lambda request: httpx.Response(200, json=envelope),
    )
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder"))


@pytest.mark.parametrize("duplicate_location", ["envelope", "block"])
def test_http_service_json_duplicate_fields_fail_closed(
    monkeypatch, duplicate_location,
):
    block = json.dumps({"type": "text", "text": json.dumps(GOOD_MODEL)})
    if duplicate_location == "envelope":
        # Previously the last content field would be silently accepted.
        response_json = '{"content":[],"content":[' + block + "]}"
    else:
        # Previously a duplicate text field inside the content block won.
        response_json = (
            '{"content":[{"type":"text","text":"bad","text":'
            + json.dumps(json.dumps(GOOD_MODEL)) + "}]}"
        )
    _mock_http_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=response_json.encode("utf-8"),
            headers={"content-type": "application/json"},
        ),
    )
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder"))


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
        "\u2028",  # Unicode line separator (renders as another line).
        "\u2029",  # Unicode paragraph separator.
        "\u200b",  # Zero-width space.
        "\u202e",  # Right-to-left override.
        "\u2066",  # Left-to-right isolate.
        "\x7f",    # ASCII delete/control (not caught by ord < 32).
        "\n",      # Actual newline, even after trim.
        "\t",      # Tab, even after trim.
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


@pytest.mark.parametrize(
    "unsafe",
    [
        "\n",      # A forged new preview field could appear on the next line.
        "\r",      # A control character can overwrite terminal-style content.
        "\t",
        "\u200b",  # Zero-width, visually misleading annotations.
        "\u202e",  # Bidirectional override.
        "\u2066",  # Bidirectional isolate.
        "\u2028",  # Unicode line separator.
        "\u2029",  # Unicode paragraph separator.
        "\x00",
        "\x7f",
    ],
)
def test_vision_notes_refuse_invisible_multiline_or_bidi_spoofing(unsafe):
    for notes in (
        "mapped SL 2343" + unsafe,
        unsafe + "mapped TP1 2353",
        "mapped SL 2343" + unsafe + "Symbol: BTCUSD",
    ):
        result = _parse_model_json(
            json.dumps({**GOOD_MODEL, "notes": notes}), engine="claude",
        )
        _must_refuse(result)


def test_vision_notes_controls_fail_closed_through_http_envelope(monkeypatch):
    # The operator preview renders notes directly; hostile model content
    # must not reach it even when the service envelope itself is well formed.
    model = {**GOOD_MODEL, "notes": "mapped entry" + "\nDirection: SELL"}
    envelope = {"content": [{"type": "text", "text": json.dumps(model)}]}
    _mock_http_client(monkeypatch, lambda request: httpx.Response(200, json=envelope))
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder"))


def test_vision_notes_allow_printable_international_text():
    # Reject rendering controls without needlessly excluding readable notes.
    notes = "Printed entry 2348; café / 東京"
    result = _parse_model_json(
        json.dumps({**GOOD_MODEL, "notes": notes}), engine="claude",
    )
    assert result.readable is True
    assert result.raw_text == TRADE
    assert result.notes == notes


def test_vision_model_json_is_bounded_before_parsing():
    # An untrusted service may violate the upstream 400-token output setting.
    # Neither an oversized plain response nor deeply nested JSON is a signal.
    for text in ("x" * 8193, "[" * 5000 + "]" * 5000):
        _must_refuse(_parse_model_json(text, engine="claude"))



def _overlong_numeric_model_json():
    # Below the 8,192-character input cap, but Python 3.11+ may raise
    # ValueError when decoding an integer token exceeding 4,300 digits.
    return (
        '{"readable":true,"signal_text":' + json.dumps(TRADE)
        + ',"confidence":"HIGH","notes":' + ("9" * 5000) + "}"
    )


@pytest.mark.parametrize("embedded_in_prose", [False, True])
def test_vision_model_json_overlong_integer_refuses_without_exception(embedded_in_prose):
    model_text = _overlong_numeric_model_json()
    if embedded_in_prose:
        model_text = "preview " + model_text + " end"
    assert len(model_text) < 8192
    _must_refuse(_parse_model_json(model_text, engine="claude"))


def test_vision_http_model_integer_refuses_without_server_error(monkeypatch):
    # The HTTP envelope itself is well-formed and within the raw byte bound.
    envelope = {"content": [{"type": "text", "text": _overlong_numeric_model_json()}]}
    _mock_http_client(monkeypatch, lambda request: httpx.Response(200, json=envelope))
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder"))

def test_streamed_gzip_response_is_refused_without_reading_or_decompressing(monkeypatch):
    # httpx.iter_bytes() decompresses a transport chunk before splitting it.
    # Prove we refuse compressed responses BEFORE even reading the raw stream.
    valid_large_envelope = json.dumps({
        "content": [{"type": "text", "text": json.dumps(GOOD_MODEL)}],
        "padding": "x" * 1_000_000,
    }).encode("utf-8")

    class TrackedGzipStream(httpx.SyncByteStream):
        def __init__(self, data):
            self.data = data
            self.consumed = False

        def __iter__(self):
            self.consumed = True
            yield self.data

    stream = TrackedGzipStream(gzip.compress(valid_large_envelope))

    def compressed_response(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, stream=stream,
        )

    _mock_http_client(monkeypatch, compressed_response)
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder"))
    assert stream.consumed is False


def test_http_envelope_size_bound_rejects_otherwise_valid_vision_json(monkeypatch):
    # A small valid model answer inside a giant upstream envelope must not
    # pass after an unbounded response read. MockTransport is fully offline.
    envelope = {
        "content": [{"type": "text", "text": json.dumps(GOOD_MODEL)}],
        "padding": "x" * 65536,
    }
    _mock_http_client(
        monkeypatch, lambda request: httpx.Response(200, json=envelope),
    )
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder"))


@pytest.mark.parametrize("surrounding_first", [False, True])
def test_multiblock_model_text_refuses_oversize_even_if_trim_would_hide_it(
    monkeypatch, surrounding_first,
):
    # Joining then stripping could previously hide arbitrarily many spaces.
    model = json.dumps(GOOD_MODEL)
    blocks = [" " * 8192, model] if surrounding_first else [model, " " * 8192]
    envelope = {"content": [{"type": "text", "text": item} for item in blocks]}
    _mock_http_client(
        monkeypatch, lambda request: httpx.Response(200, json=envelope),
    )
    _must_refuse(ClaudeExtractor().extract(b"offline-placeholder"))


def test_model_text_at_exact_incremental_limit_remains_compatible(monkeypatch):
    model = json.dumps(GOOD_MODEL)
    envelope = {
        "content": [
            {"type": "text", "text": " " * (8192 - len(model))},
            {"type": "text", "text": model},
        ],
    }
    _mock_http_client(
        monkeypatch, lambda request: httpx.Response(200, json=envelope),
    )
    result = ClaudeExtractor().extract(b"offline-placeholder")
    assert result.readable is True
    assert result.raw_text == TRADE


def test_vision_signal_allows_plain_ascii_surrounding_spaces():
    result = _parse_model_json(
        json.dumps({**GOOD_MODEL, "signal_text": "  " + TRADE + "  "}),
        engine="claude",
    )
    assert result.readable is True
    assert result.raw_text == TRADE
