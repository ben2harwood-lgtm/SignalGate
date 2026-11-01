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


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///./wrong-hosted.db",
        "sqlite+pysqlite:///./wrong-hosted.db",
        "mysql+pymysql://synthetic:never-expose@localhost/demo",
        "mssql+pyodbc://synthetic:never-expose@localhost/demo",
        # PostgreSQL dialect alone is insufficient: libpq may silently use
        # an implicit local socket or default database if fields are absent.
        "postgresql://",
        "postgresql:///demo",
        "postgresql://synthetic:never-expose@/demo",
        "postgresql://synthetic:never-expose@localhost/",
        "postgresql://synthetic:never-expose@localhost",
        # A libpq query option can silently replace the explicit URL server,
        # identity or database; this is not the permitted SSL query case.
        "postgresql://synthetic:never-expose@db/demo?host=/var/run/postgresql",
        "postgresql://synthetic:never-expose@db/demo?hostaddr=127.0.0.1",
        "postgresql://synthetic:never-expose@db/demo?port=5433",
        "postgresql://synthetic:never-expose@db/demo?dbname=another",
        "postgresql://synthetic:never-expose@db/demo?user=other",
        "postgresql://synthetic:never-expose@db/demo?password=other",
        "postgresql://synthetic:never-expose@db/demo?service=local",
        "not-a-database-url",
    ],
)
def test_hosted_demo_rejects_non_postgresql_or_malformed_database_url(
    monkeypatch, database_url
):
    settings = _local_settings(monkeypatch)
    settings.require_license = True
    settings.backend_base_url = "https://staging.example.invalid"
    settings.database_url = database_url
    settings.ea_api_key = "e" * 40
    settings.admin_api_key = "a" * 40
    settings.registration_api_key = "r" * 40

    with pytest.raises(RuntimeError, match="Hosted mode requires PostgreSQL") as error:
        settings.validate_startup()
    assert "never-expose" not in str(error.value)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgres://synthetic:fake@localhost/demo",
        "postgresql://synthetic:fake@localhost/demo",
        "postgresql+psycopg2://synthetic:fake@localhost/demo",
        "postgresql://synthetic:fake@localhost/demo?sslmode=require",
    ],
)
def test_hosted_demo_allows_postgresql_dialects_without_connecting(
    monkeypatch, database_url
):
    settings = _local_settings(monkeypatch)
    settings.require_license = True
    settings.backend_base_url = "https://staging.example.invalid"
    settings.database_url = database_url
    settings.ea_api_key = "e" * 40
    settings.admin_api_key = "a" * 40
    settings.registration_api_key = "r" * 40
    settings.validate_startup()



@pytest.mark.parametrize(
    "base_url",
    [
        "https://",
        "https:///missing-authority",
        "https://operator:synthetic-secret@demo.example.invalid",
        "https://demo.example.invalid:invalid-port",
        "https://demo.example.invalid?token=synthetic-secret",
        "https://demo.example.invalid/#synthetic-secret",
        "https://demo.example.invalid\\untrusted",
        "https://demo.example.invalid\r\nX-Leak: synthetic-secret",
        " https://demo.example.invalid",
        "https://demo.example.invalid ",
    ],
)
def test_hosted_demo_rejects_invalid_or_credentialled_https_base_url(
    monkeypatch, base_url
):
    settings = _local_settings(monkeypatch)
    settings.require_license = True
    settings.database_url = "postgresql://synthetic:fake@localhost/demo"
    settings.backend_base_url = base_url
    settings.ea_api_key = "e" * 40
    settings.admin_api_key = "a" * 40
    settings.registration_api_key = "r" * 40

    with pytest.raises(RuntimeError, match="HTTPS BACKEND_BASE_URL") as error:
        settings.validate_startup()
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize(
    "base_url",
    ["https://demo.example.invalid", "https://demo.example.invalid:8443/api"],
)
def test_hosted_demo_accepts_valid_https_base_url_without_connecting(
    monkeypatch, base_url
):
    settings = _local_settings(monkeypatch)
    settings.require_license = True
    settings.database_url = "postgresql://synthetic:fake@localhost/demo"
    settings.backend_base_url = base_url
    settings.ea_api_key = "e" * 40
    settings.admin_api_key = "a" * 40
    settings.registration_api_key = "r" * 40
    settings.validate_startup()

@pytest.mark.parametrize(
    ("source_key", "target_key", "suffix"),
    [
        ("ea_api_key", "admin_api_key", ""),
        ("ea_api_key", "registration_api_key", ""),
        ("admin_api_key", "registration_api_key", ""),
        ("ea_api_key", "admin_api_key", " \t"),
    ],
)
def test_hosted_demo_rejects_reused_service_secrets_without_leaking_values(
    monkeypatch, source_key, target_key, suffix
):
    # Pure startup-settings preflight: no database, broker or network access.
    settings = _local_settings(monkeypatch)
    settings.require_license = True
    settings.database_url = "postgresql://synthetic:fake@localhost/demo"
    settings.backend_base_url = "https://staging.example.invalid"
    settings.ea_api_key = "e" * 40
    settings.admin_api_key = "a" * 40
    settings.registration_api_key = "r" * 40
    copied_secret = getattr(settings, source_key)
    setattr(settings, target_key, copied_secret + suffix)

    with pytest.raises(RuntimeError, match="distinct EA_API_KEY") as error:
        settings.validate_startup()
    assert copied_secret not in str(error.value)


@pytest.mark.parametrize(
    ("key", "bad_value"),
    [
        ("REQUIRE_LICENSE", ""),
        ("REQUIRE_LICENSE", "ture"),
        ("REQUIRE_LICENSE", "synthetic-secret-not-a-boolean"),
        ("DEMO_ONLY_MODE", ""),
        ("DEMO_ONLY_MODE", "invalid-boolean"),
    ],
)
def test_security_mode_flags_refuse_invalid_booleans_before_startup(
    monkeypatch, key, bad_value
):
    # Configuration is parsed without creating the database, opening a
    # listener, contacting Telegram or reaching a demo broker.
    _local_settings(monkeypatch)
    monkeypatch.setenv(key, bad_value)
    with pytest.raises(RuntimeError, match=rf"^{key} requires an explicit boolean") as error:
        Settings()
    if bad_value:
        assert bad_value not in str(error.value)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("REQUIRE_LICENSE", " TRUE ", True),
        ("REQUIRE_LICENSE", "off", False),
        ("REQUIRE_LICENSE", "0", False),
        ("DEMO_ONLY_MODE", "YES", True),
        ("DEMO_ONLY_MODE", "false", False),
    ],
)
def test_security_mode_flags_preserve_explicit_boolean_spellings(
    monkeypatch, key, value, expected
):
    _local_settings(monkeypatch)
    monkeypatch.setenv(key, value)
    parsed = Settings()
    assert getattr(parsed, key.lower()) == expected


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
    ("proxy_header", "proxy_value"),
    [
        ("Forwarded", "for=192.0.2.22;host=public.example.invalid"),
        ("X-Forwarded-For", "192.0.2.22"),
        ("X-Forwarded-Host", "public.example.invalid"),
        ("X-Forwarded-Proto", "https"),
        ("X-Forwarded-Port", "443"),
        ("X-Real-IP", "192.0.2.22"),
        ("X-Original-Host", "public.example.invalid"),
        ("X-Envoy-External-Address", "192.0.2.22"),
        ("CF-Connecting-IP", "192.0.2.22"),
        ("True-Client-IP", "192.0.2.22"),
        ("Via", "1.1 public-proxy"),
    ],
)
def test_local_ingress_refuses_forwarded_proxy_metadata_despite_loopback_host(
    client, caplog, proxy_header, proxy_value
):
    # A common proxy can rewrite Host to 127.0.0.1 and still leak its
    # forwarding headers to Uvicorn. Reject before the local-auth route runs.
    # This is synthetic: a proxy stripping all headers remains issue #108.
    caplog.set_level(logging.WARNING, logger="signalgate.request")
    response = client.get(
        "/livez",
        headers={
            "Host": "127.0.0.1:8000",
            proxy_header: proxy_value,
            "X-Request-Id": "untrusted-proxy-marker",
        },
    )
    assert response.status_code == 403
    assert response.text == "Local demo ingress refused"
    assert response.headers["X-Request-Id"] != "untrusted-proxy-marker"
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "signalgate.request"
        and "LOCAL_DEMO_INGRESS_REFUSED" in record.getMessage()
    ]
    assert len(events) == 1
    logged = json.dumps(events[0])
    assert proxy_value not in logged
    assert "untrusted-proxy-marker" not in logged


def test_hosted_routes_do_not_apply_local_proxy_metadata_refusal(client, monkeypatch):
    # The hosted listener has its own authenticated/proxy deployment boundary.
    monkeypatch.setattr(main_module.settings, "require_license", True)
    response = client.get(
        "/livez", headers={"X-Forwarded-For": "192.0.2.22"}
    )
    assert response.status_code == 200


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
