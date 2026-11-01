"""Broker-free rehearsal must not forward ambient operator credentials to pytest.

These tests use synthetic strings and temporary directories; no broker, backend,
remote network service, real token or credential is needed.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run_broker_free_rehearsal.py"
spec = importlib.util.spec_from_file_location("sg_broker_free_rehearsal", SCRIPT)
assert spec and spec.loader
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


def test_candidate_pytest_environment_discards_ambient_credentials(monkeypatch, tmp_path):
    poisoned = {
        "GITHUB_TOKEN": "SYNTHETIC-GITHUB-CANARY",
        "AWS_SECRET_ACCESS_KEY": "SYNTHETIC-CLOUD-CANARY",
        "SIGNALGATE_PROVIDER_API_KEY": "SYNTHETIC-PROVIDER-CANARY",
        "PYTHONPATH": "/synthetic-import-hook",
        "PYTHONSTARTUP": "/synthetic-startup-hook",
        "PYTEST_ADDOPTS": "--synthetic-operator-option",
        "HTTP_PROXY": "http://untrusted.invalid:8888",
        "HTTPS_PROXY": "http://untrusted.invalid:8888",
    }
    for key, value in poisoned.items():
        monkeypatch.setenv(key, value)

    env = rehearsal.rehearsal_test_env(tmp_path)

    for key, value in poisoned.items():
        assert key not in env, f"ambient {key} leaked into candidate test environment"
        assert value not in env.values()
    assert env["TELEGRAM_BOT_TOKEN"] == ""
    assert env["ADMIN_API_KEY"] == ""
    assert env["SIGNAL_PROVIDER_API_KEY"] == ""


def test_rehearsal_env_overrides_host_database_and_demo_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic-secret.invalid/db")
    monkeypatch.setenv("SIGNALGATE_TEST_DATABASE_URL", "postgresql://synthetic-secret.invalid/tests")
    monkeypatch.setenv("DEMO_ONLY_MODE", "false")
    monkeypatch.setenv("REQUIRE_LICENSE", "true")
    monkeypatch.setenv("HOME", "/synthetic-secret-home")

    env = rehearsal.rehearsal_test_env(tmp_path)

    db_url = f"sqlite:///{tmp_path / 'rehearsal.db'}"
    assert env["DATABASE_URL"] == db_url
    assert env["SIGNALGATE_TEST_DATABASE_URL"] == db_url
    assert env["DEMO_ONLY_MODE"] == "true"
    assert env["REQUIRE_LICENSE"] == "false"
    assert env["HOME"] == str(tmp_path / "rehearsal-home")
    assert env["USERPROFILE"] == env["HOME"]
    assert env["TMPDIR"] == str(tmp_path / "rehearsal-tmp")
    assert env["TMP"] == env["TEMP"] == env["TMPDIR"]
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert Path(env["HOME"]).is_dir()
    assert Path(env["TMPDIR"]).is_dir()
    if os.name == "posix":
        assert stat.S_IMODE(Path(env["HOME"]).stat().st_mode) == 0o700
        assert stat.S_IMODE(Path(env["TMPDIR"]).stat().st_mode) == 0o700


def test_rehearsal_run_uses_credential_scrubbed_environment():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "env = rehearsal_test_env(scratch)" in source
    assert "env = os.environ.copy()" not in source
    assert "actual_mt5_demo_acceptance" in source
    assert '"OPEN"' in source
