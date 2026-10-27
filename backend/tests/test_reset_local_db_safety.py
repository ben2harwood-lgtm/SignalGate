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


@pytest.mark.parametrize("target_kind", ["external", "other_canonical"])
def test_reset_rejects_canonical_file_symlink_without_mutating_target(
    tmp_path, target_kind
):
    """A canonical-looking symlink must not bless its resolved external target."""
    root = tmp_path / "source"
    root.mkdir()
    backend = root / "backend"
    backend.mkdir()
    dest = (
        tmp_path / "customer.db"
        if target_kind == "external"
        else backend / "signalgate.db"
    )
    dest.write_bytes(b"sentinel: do not alter")
    (root / "signalgate.db").symlink_to(dest)

    gate = _gate()
    # Only adjust the function's isolated runpy globals; no actual repo DB
    # or reset command is touched.
    gate.__globals__["_ROOT"] = root
    gate.__globals__["_BACKEND"] = backend
    with pytest.raises(RuntimeError, match="must not be a symlink"):
        gate(
            "sqlite:///./signalgate.db",
            demo_only_mode=True,
            require_license=False,
            cwd=root,
        )
    assert dest.read_bytes() == b"sentinel: do not alter"


def test_reset_rejects_driver_normalized_directory_symlink_dotdot(tmp_path):
    """SQLite removes '..' lexically before following symlinks; mirror its target."""
    root = tmp_path / "source"
    backend = root / "backend"
    child = root / "child"
    backend.mkdir(parents=True)
    child.mkdir()
    (backend / "link").symlink_to(child, target_is_directory=True)
    original = root / "signalgate.db"
    original.write_bytes(b"safe repository db")
    outside = tmp_path / "customer.db"
    outside.write_bytes(b"external sentinel unchanged")
    (backend / "signalgate.db").symlink_to(outside)

    gate = _gate()
    gate.__globals__["_ROOT"] = root
    gate.__globals__["_BACKEND"] = backend
    tricky = backend / "link" / ".." / "signalgate.db"
    with pytest.raises(RuntimeError, match="must not be a symlink"):
        gate(
            "sqlite:///" + str(tricky),
            demo_only_mode=True,
            require_license=False,
            cwd=backend,
        )
    assert original.read_bytes() == b"safe repository db"
    assert outside.read_bytes() == b"external sentinel unchanged"


def test_reset_refuses_cached_relative_engine_after_working_directory_change(
    tmp_path, monkeypatch
):
    """Never trust engine.url after SQLAlchemy already bound a filename."""
    import sys
    from types import ModuleType
    from sqlalchemy import create_engine

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    engine = create_engine("sqlite:///./signalgate.db")  # does not connect
    cached = ModuleType("app.database")
    cached.engine = engine
    monkeypatch.setitem(sys.modules, "app.database", cached)

    # The raw relative engine URL still looks local after this cwd switch, but
    # its original connection creator was bound outside the canonical repo.
    monkeypatch.chdir(ROOT / "backend")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./signalgate.db")
    monkeypatch.setenv("REQUIRE_LICENSE", "false")
    monkeypatch.setenv("DEMO_ONLY_MODE", "true")
    main = runpy.run_path(str(SCRIPT), run_name="signalreset_preflight_test")["main"]
    try:
        with pytest.raises(RuntimeError, match="pre-existing database engine"):
            main(["--confirm-local-demo-reset"])
        assert not (other / "signalgate.db").exists()
    finally:
        engine.dispose()
