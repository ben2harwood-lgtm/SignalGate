"""Reject ambiguous operator API origins before any credentialled HTTP request.

Synthetic strings and placeholder keys only. No network, broker or provider.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load("scripts/pilot_preflight.py", "sg_origin_guard_preflight")
snapshot = _load("scripts/pilot_ops_snapshot.py", "sg_origin_guard_snapshot")


@pytest.mark.parametrize(
    ("origin", "canonical"),
    [
        ("http://localhost:8000/", "http://localhost:8000"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://[::1]:8000/", "http://[::1]:8000"),
        ("https://pilot.example.invalid", "https://pilot.example.invalid"),
        ("https://pilot.example.invalid:8443/", "https://pilot.example.invalid:8443"),
    ],
)
def test_existing_loopback_and_remote_https_origins_remain_supported(origin, canonical):
    assert preflight.validate_backend_url(origin) == canonical
    assert snapshot.validate_backend_url(origin) == canonical


@pytest.mark.parametrize(
    "origin",
    [
        "",
        " https://pilot.example.invalid",
        "https://pilot.example.invalid ",
        "https://pilot.example.invalid\t",
        "https://pilot.example.invalid\\\\path",
        "https://pilot.example.invalid\\\\@other.invalid",
        "https://@pilot.example.invalid",
        "https://user:synthetic@pilot.example.invalid",
        "https://pilot.example.invalid%2f.other.invalid",
        "https://pilot.example.invalid:broken",
        "https://pilot.example.invalid:",
        "https://pilot.example.invalid//",
        "https://pilot.example.invalid/pilot",
        "https://pilot.example.invalid?secret=SYNTHETIC",
        "https://pilot.example.invalid#",
        "https://pilot.example.invalid?",
        "http://pilot.example.invalid",
        "http://localhost.evil.invalid",
        "http://192.0.2.5:8000",
        "http://[::]:8000",
    ],
)
def test_preflight_and_snapshot_refuse_bad_origin_before_constructing_client(
    monkeypatch, origin
):
    constructed = []

    def forbidden_client(*_args, **_kwargs):
        constructed.append(True)
        raise AssertionError("HTTP client constructed for invalid origin")

    monkeypatch.setattr(httpx, "Client", forbidden_client)
    with pytest.raises(ValueError):
        preflight.run_preflight(
            backend=origin,
            provider_id="PROVIDER-SYNTHETIC",
            provider_api_key="SYNTHETIC-KEY",
            declared_candidate_sha="a" * 40,
            require_feeds_paused=True,
        )
    with pytest.raises(ValueError):
        snapshot.collect(
            backend=origin,
            admin_id="SYNTHETIC-ID",
            admin_api_key="SYNTHETIC-KEY",
            candidate_sha="a" * 40,
        )
    assert constructed == []


def test_both_credentialled_operator_clients_disable_ambient_proxy_and_ca(monkeypatch):
    """Constructor-level negative guard; no transport or network is created."""
    class BlockNetwork(RuntimeError):
        pass

    created = []

    def blocked_client(*_args, **kwargs):
        assert kwargs["base_url"] == "https://pilot.example.invalid"
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        created.append(True)
        raise BlockNetwork("synthetic: no network")

    # These values must not influence outbound privileged HTTP client setup.
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/untrusted/ca.pem")
    monkeypatch.setattr(httpx, "Client", blocked_client)

    with pytest.raises(BlockNetwork, match="synthetic: no network"):
        preflight.run_preflight(
            backend="https://pilot.example.invalid",
            provider_id="PROVIDER-SYNTHETIC",
            provider_api_key="SYNTHETIC-KEY",
            declared_candidate_sha="a" * 40,
            require_feeds_paused=True,
        )

    with pytest.raises(BlockNetwork, match="synthetic: no network"):
        snapshot.collect(
            backend="https://pilot.example.invalid",
            admin_id="SYNTHETIC-ID",
            admin_api_key="SYNTHETIC-KEY",
            candidate_sha="a" * 40,
        )

    assert len(created) == 2
