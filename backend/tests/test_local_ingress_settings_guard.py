"""Offline guardrails for explicitly public local-header demo configuration.

These checks validate startup settings only. They do NOT prove that an
operator-supplied Uvicorn --host or reverse proxy cannot expose loopback-configured
local auth, and they do not make an external provider/demo pilot acceptable.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, local_demo_http_ingress_is_loopback
from app.database import engine as test_engine
import app.main as main_module


def _local_settings(monkeypatch) -> Settings:
    monkeypatch.setenv("DEMO_ONLY_MODE", "true")
    monkeypatch.setenv("REQUIRE_LICENSE", "false")
    monkeypatch.setenv("BACKEND_HOST", "127.0.0.1")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
    return Settings()


@pytest.mark.parametrize(
    ("bind_host", "advertised_url"),
    [
        ("127.0.0.1", "http://127.0.0.1:8000"),
        ("localhost", "http://localhost:8000"),
        ("::1", "http://[::1]:8000"),
        ("127.0.0.2", "https://127.0.0.1:8443"),
    ],
)
def test_local_demo_accepts_explicit_loopback_settings(monkeypatch, bind_host, advertised_url):
    settings = _local_settings(monkeypatch)
    settings.backend_host = bind_host
    settings.backend_base_url = advertised_url
    settings.validate_startup()


@pytest.mark.parametrize(
    "bind_host",
    [
        "", "0.0.0.0", "::", "192.0.2.10", "localhost.example.invalid",
        "public.example.invalid", "127.0.0.1.evil.invalid",
    ],
)
def test_local_demo_refuses_public_or_deceptive_bind(monkeypatch, bind_host):
    settings = _local_settings(monkeypatch)
    settings.backend_host = bind_host
    with pytest.raises(RuntimeError, match="loopback BACKEND_HOST and BACKEND_BASE_URL"):
        settings.validate_startup()


@pytest.mark.parametrize(
    "advertised_url",
    [
        "https://api.example.invalid",
        "http://0.0.0.0:8000",
        "http://192.0.2.44:8000",
        "http://127.0.0.1.evil.invalid",
        "http://localhost.evil.invalid",
        "http://user:secret@localhost:8000",
        "http://localhost@api.example.invalid",
        "ftp://127.0.0.1:8000",
        "http://[::1",
        "http://127.0.0.1:invalid",
        "http://127.0.0.1:8000/?redirect=https://api.example.invalid",
        "http://127.0.0.1:8000/#external",
        "//localhost:8000",
        "",
    ],
)
def test_local_demo_refuses_external_or_malformed_base_url(monkeypatch, advertised_url):
    settings = _local_settings(monkeypatch)
    settings.backend_base_url = advertised_url
    with pytest.raises(RuntimeError, match="loopback BACKEND_HOST and BACKEND_BASE_URL") as error:
        settings.validate_startup()
    assert "secret" not in str(error.value)


def test_hosted_demo_ingress_still_uses_licensed_secret_and_https_gates(monkeypatch):
    _local_settings(monkeypatch)
    monkeypatch.setenv("REQUIRE_LICENSE", "true")
    monkeypatch.setenv("DEMO_ONLY_MODE", "true")
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("BACKEND_BASE_URL", "https://staging.example.invalid")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic:fake@localhost/demo")
    monkeypatch.setenv("EA_API_KEY", "e" * 40)
    monkeypatch.setenv("ADMIN_API_KEY", "a" * 40)
    monkeypatch.setenv("REGISTRATION_API_KEY", "r" * 40)
    Settings().validate_startup()


def test_real_asgi_startup_refuses_advertised_public_local_auth_before_db(monkeypatch):
    # The SQLite/Postgres fixture owns its synthetic per-test schema. This
    # assertion concerns actual ASGI startup order, not fixture construction.
    monkeypatch.setattr(main_module.settings, "demo_only_mode", True)
    monkeypatch.setattr(main_module.settings, "require_license", False)
    monkeypatch.setattr(main_module.settings, "backend_host", "127.0.0.1")
    monkeypatch.setattr(
        main_module.settings, "backend_base_url", "https://public.example.invalid"
    )
    monkeypatch.setattr(
        main_module, "init_db",
        lambda: pytest.fail("init_db reached before unsafe ingress was refused"),
    )
    monkeypatch.setattr(
        main_module, "seed_settings",
        lambda: pytest.fail("seed_settings reached before unsafe ingress was refused"),
    )
    with pytest.raises(RuntimeError, match="loopback BACKEND_HOST and BACKEND_BASE_URL"):
        with TestClient(main_module.app):
            pytest.fail("ASGI lifespan allowed advertised public local-auth mode")


@pytest.mark.parametrize(
    ("bound_server", "host", "allowed"),
    [
        (("127.0.0.1", 8000), "127.0.0.1:8000", True),
        (("::1", 8000), "[::1]:8000", True),
        (("localhost", 8000), "localhost:8000", True),
        (("127.0.0.1", 8000), "localhost", True),
        (("0.0.0.0", 8000), "127.0.0.1:8000", False),
        (("192.0.2.22", 8000), "localhost:8000", False),
        (("127.0.0.1", 8000), "api.example.invalid", False),
        (("127.0.0.1", 8000), "127.0.0.1.evil.invalid", False),
        (("127.0.0.1", 8000), "user@127.0.0.1", False),
        (("127.0.0.1", 8000), "127.0.0.1:broken", False),
        (("127.0.0.1", 8000), "127.0.0.1\r\nX-Evil: yes", False),
        (("127.0.0.1", 8000), "", False),
        (("127.0.0.1", 8000), None, False),
        (None, "127.0.0.1:8000", False),
        (("testserver", 80), "127.0.0.1", False),
    ],
)
def test_actual_asgi_listener_and_untrusted_host_must_both_be_local(
    bound_server, host, allowed
):
    # Pure offline scope simulation; never opens a public listening socket.
    assert local_demo_http_ingress_is_loopback(bound_server, host) is allowed


@pytest.mark.parametrize(
    ("synthetic_bound_address", "host_header"),
    [
        ("0.0.0.0", "127.0.0.1:8000"),
        ("192.0.2.44", "localhost:8000"),
        ("127.0.0.1", "api.example.invalid"),
        ("127.0.0.1", "127.0.0.1.evil.invalid"),
    ],
)
def test_local_identity_routes_refuse_nonlocal_asgi_ingress(
    monkeypatch, synthetic_bound_address, host_header
):
    # Settings claim a local service, but TestClient simulates a contradictory
    # actual server tuple/Host. This is NOT a network or proxy penetration test.
    monkeypatch.setattr(main_module.settings, "require_license", False)
    monkeypatch.setattr(main_module.settings, "demo_only_mode", True)
    monkeypatch.setattr(main_module.settings, "backend_host", "127.0.0.1")
    monkeypatch.setattr(
        main_module.settings, "backend_base_url", "http://127.0.0.1:8000"
    )
    # #125 refuses unlicensed PostgreSQL app startup. This test checks only
    # ingress middleware against synthetic ASGI address/Host combinations;
    # the PostgreSQL matrix schema is already isolated by fresh_db. Stub just
    # this test client lifespan, never the separate real-startup negative test.
    if test_engine.url.get_backend_name() == "postgresql":
        monkeypatch.setattr(main_module, "init_db", lambda: None)
    with TestClient(
        main_module.app, base_url=f"http://{synthetic_bound_address}:8000"
    ) as test_client:
        refused = test_client.get("/livez", headers={"Host": host_header})
        assert refused.status_code == 403
        assert refused.text == "Local demo ingress refused"
        assert "api" not in refused.headers.get("server", "").lower()


def test_local_ingress_allows_normal_loopback_request(client):
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_ingress_refuses_external_host_even_on_loopback_listener(client):
    # Route execution is denied even if a proxy retains a public Host.
    response = client.get("/livez", headers={"Host": "public.example.invalid"})
    assert response.status_code == 403
    assert response.text == "Local demo ingress refused"


@pytest.mark.parametrize(
    "host_values",
    [
        [("Host", "127.0.0.1:8000"), ("Host", "public.example.invalid")],
        [("Host", "127.0.0.1:8000"), ("Host", "127.0.0.1:8000")],
    ],
)
def test_local_ingress_refuses_duplicate_host_headers(client, host_values):
    # A reverse proxy and application must never disagree over which Host
    # supplied authority for a local-only request.
    response = client.get("/livez", headers=host_values)
    assert response.status_code == 403
    assert response.text == "Local demo ingress refused"


@pytest.mark.parametrize(
    "untrusted_headers",
    [
        {"Host": "public.example.invalid", "X-Request-Id": "attacker-private-token"},
        [
            ("Host", "127.0.0.1:8000"),
            ("Host", "public.example.invalid"),
            ("X-Request-Id", "attacker-private-token"),
        ],
    ],
)
def test_refused_local_ingress_is_audited_without_logging_host_or_supplied_id(
    client, caplog, untrusted_headers
):
    caplog.set_level(logging.WARNING, logger="signalgate.request")
    response = client.get("/livez", headers=untrusted_headers)
    assert response.status_code == 403
    request_id = response.headers["X-Request-Id"]
    assert len(request_id) == 32
    assert all(ch in "0123456789abcdef" for ch in request_id)
    assert request_id != "attacker-private-token"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"

    entries = [
        json.loads(r.getMessage()) for r in caplog.records
        if r.name == "signalgate.request" and
        "LOCAL_DEMO_INGRESS_REFUSED" in r.getMessage()
    ]
    assert len(entries) == 1
    event = entries[0]
    assert event["event"] == "http_request"
    assert event["request_id"] == request_id
    assert event["status"] == 403
    assert event["path"] == "[local-ingress-refused]"
    serialized = json.dumps(event)
    assert "public.example.invalid" not in serialized
    assert "attacker-private-token" not in serialized
