"""The convenience launchers must not expose local-header demo authentication."""
from __future__ import annotations

from pathlib import Path
import shlex

import pytest


_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("launcher", ["Start Backend.command", "Start Backend.bat"])
def test_double_click_backend_launcher_binds_only_loopback(launcher: str) -> None:
    """A missing/overridden --host would reopen the local-auth LAN exposure."""
    text = (_ROOT / launcher).read_text(encoding="utf-8")
    commands = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("uvicorn app.main:app ")
    ]
    assert len(commands) == 1, "expected one explicit Uvicorn launch command"
    words = shlex.split(commands[0])
    assert words[:2] == ["uvicorn", "app.main:app"]
    host_values = [words[i + 1] for i, word in enumerate(words[:-1]) if word == "--host"]
    assert host_values == ["127.0.0.1"], "local demo must not bind a public interface"
