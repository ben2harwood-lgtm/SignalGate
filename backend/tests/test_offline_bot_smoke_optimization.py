"""The offline bot smoke must not claim PASS when Python elides assertions."""
from pathlib import Path
import subprocess
import sys

import pytest


SMOKE = Path(__file__).resolve().parents[2] / "scripts" / "verify_telegram_bot_wiring.py"


@pytest.mark.parametrize(
    ("python_flags", "optimized_env"),
    [
        (["-O"], False),
        (["-OO"], False),
        ([], True),
    ],
)
def test_offline_bot_smoke_refuses_python_optimisation(python_flags, optimized_env):
    # The guard runs before any third-party import, token handling or network.
    # Give this child no inherited credentials or provider configuration.
    env = {"PYTHONNOUSERSITE": "1"}
    if optimized_env:
        env["PYTHONOPTIMIZE"] = "1"
    result = subprocess.run(
        [sys.executable, *python_flags, str(SMOKE)],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    assert result.returncode != 0
    assert "offline smoke refuses optimized Python" in result.stderr
    assert "PASS" not in result.stdout
