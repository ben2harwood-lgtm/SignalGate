"""Non-destructive regressions for the local demo reset's fail-closed gate."""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "reset_local_db.py"


def _gate():
    # run_name prevents the CLI from executing. Never call the destructive path.
    return runpy.run_path(str(SCRIPT), run_name="signalreset_preflight_test")[
        "_require_local_demo_target"
    ]


def test_reset_accepts_only_canonical_local_demo_files():
    gate = _gate()
    for cwd in (ROOT, ROOT / "backend"):
        result = gate(
            "sqlite:///./signalgate.db",
            demo_only_mode=True,
            require_license=False,
            cwd=cwd,
        )
        assert result == (cwd / "signalgate.db").resolve()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://operator:do-not-print@localhost/customer",
        "postgres://operator:do-not-print@localhost/customer",
        "sqlite:///:memory:",
        "sqlite://",
        "sqlite:///../../customer.db",
        "sqlite:////tmp/signalgate.db",
        "sqlite:///file:signalgate.db?uri=true",
        "sqlite+pysqlite:///./signalgate.db",
        "not-a-database-url",
    ],
)
def test_reset_refuses_remote_noncanonical_or_ambiguous_database(url):
    with pytest.raises(RuntimeError, match="Refusing reset") as err:
        _gate()(
            url,
            demo_only_mode=True,
            require_license=False,
            cwd=ROOT / "backend",
        )
    assert "do-not-print" not in str(err.value)


@pytest.mark.parametrize(
    "demo_only_mode,require_license",
    [(False, False), (True, True), (False, True)],
)
def test_reset_refuses_hosted_or_live_flags(demo_only_mode, require_license):
    with pytest.raises(RuntimeError, match="Refusing reset"):
        _gate()(
            "sqlite:///./signalgate.db",
            demo_only_mode=demo_only_mode,
            require_license=require_license,
            cwd=ROOT / "backend",
        )


def test_reset_requires_explicit_operator_flag_before_backend_import():
    main = runpy.run_path(str(SCRIPT), run_name="signalreset_preflight_test")["main"]
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_reset_refuses_postgres_before_accessing_destructive_database(monkeypatch):
    main = runpy.run_path(str(SCRIPT), run_name="signalreset_preflight_test")["main"]
    monkeypatch.setenv("DATABASE_URL", "postgresql://operator:do-not-print@localhost/customer")
    monkeypatch.setenv("DEMO_ONLY_MODE", "true")
    monkeypatch.setenv("REQUIRE_LICENSE", "false")
    with pytest.raises(RuntimeError, match="only the local demo SQLite file") as err:
        main(["--confirm-local-demo-reset"])
    assert "do-not-print" not in str(err.value)
