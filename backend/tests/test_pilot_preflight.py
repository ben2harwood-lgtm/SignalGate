"""Provider pilot preflight helper tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pilot_preflight.py"
SPEC = importlib.util.spec_from_file_location("pilot_preflight", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("https://api.example.test/", "https://api.example.test"),
    ],
)
def test_backend_url_validation(raw, expected):
    assert preflight.validate_backend_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://api.example.test",
        "https://user:pass@example.test",
        "https://api.example.test/path?secret=x",
        "ftp://api.example.test",
        "not-a-url",
    ],
)
def test_backend_url_rejects_unsafe_values(raw):
    with pytest.raises(ValueError):
        preflight.validate_backend_url(raw)


def test_mutated_secret_is_never_same():
    assert preflight.mutate_secret("sgp_example") != "sgp_example"
    assert preflight.mutate_secret("x") != "x"


def test_export_secret_field_scanner_is_recursive():
    payload = {
        "provider": {"id": "PROVIDER-1"},
        "feeds": [{"id": "FEED-1", "subscribers": [{"license_key": "never"}]}],
        "history": [{"nested": {"token_hash": "never"}}],
    }
    hits = preflight.find_forbidden_keys(payload)
    assert "$.feeds[0].subscribers[0].license_key" in hits
    assert "$.history[0].nested.token_hash" in hits


def test_export_scanner_allows_expected_operating_metadata():
    payload = {
        "provider": {"id": "PROVIDER-1", "name": "Example", "paused": True},
        "feeds": [{"id": "FEED-1", "paused": True}],
        "signals": [{"id": "SIG-1", "symbol": "XAUUSD", "direction": "BUY"}],
        "summary": {"signal_count_in_export": 1},
    }
    assert preflight.find_forbidden_keys(payload) == []


def test_candidate_sha_must_be_canonical_before_network_calls():
    with pytest.raises(ValueError):
        preflight.run_preflight(
            backend="http://127.0.0.1:8000",
            provider_id="PROVIDER-1",
            provider_api_key="sgp_example",
            declared_candidate_sha="not-a-sha",
            require_feeds_paused=True,
        )
