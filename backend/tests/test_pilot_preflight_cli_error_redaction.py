"""Preflight CLI must never print transport/validation exception text.

Synthetic exceptions only: no provider, real credentials, backend or networking.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/pilot_preflight.py"
spec = importlib.util.spec_from_file_location("sg_pilot_preflight_cli", SCRIPT)
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("SYNTHETIC_PRIVATE_RESPONSE_MARKER"),
        httpx.ConnectError("SYNTHETIC_PRIVATE_RESPONSE_MARKER"),
        OSError("SYNTHETIC_PRIVATE_RESPONSE_MARKER"),
        json.JSONDecodeError("SYNTHETIC_PRIVATE_RESPONSE_MARKER", "x", 0),
    ],
)
def test_preflight_cli_does_not_echo_sensitive_exception_message(
    monkeypatch, capsys, tmp_path, failure
):
    """Even rare transport and filesystem exception messages are untrusted."""
    monkeypatch.setenv("SIGNALGATE_PROVIDER_API_KEY", "SYNTHETIC_PRIVATE_PROVIDER_KEY")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pilot_preflight.py",
            "--backend", "http://127.0.0.1:8000",
            "--provider-id", "PROV-SYNTHETIC",
            "--candidate-sha", "a" * 40,
            "--evidence-root", str(tmp_path / "unused"),
        ],
    )

    def raise_failure(**_kwargs):
        raise failure

    monkeypatch.setattr(preflight, "run_preflight", raise_failure)
    assert preflight.main() == 2

    out = capsys.readouterr()
    all_output = out.err + out.out
    assert "preflight error" in out.err
    assert type(failure).__name__ in out.err
    assert "SYNTHETIC_PRIVATE_RESPONSE_MARKER" not in all_output
    assert "SYNTHETIC_PRIVATE_PROVIDER_KEY" not in all_output
    assert not (tmp_path / "unused").exists()
