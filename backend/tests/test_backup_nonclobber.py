"""Offline regressions for unique backup artifacts and cleanup after failure.

All PostgreSQL and age commands are synthetic executable fixtures. Actual
PostgreSQL/age interoperability remains the dedicated ephemeral CI restore job.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_postgres.sh"


def _program(directory: Path, name: str, source: str) -> None:
    program = directory / name
    program.write_text(source, encoding="utf-8")
    program.chmod(0o700)


def _synthetic_environment(tmp_path: Path) -> dict[str, str]:
    executables = tmp_path / "mock-bin"
    executables.mkdir()
    _program(
        executables,
        "date",
        "#!/bin/sh\nprintf '20261023T100000Z\\n'\n",
    )
    _program(
        executables,
        "pg_dump",
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys
output = next(arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--file="))
if os.getenv("SG_TEST_DUMP_FAIL") == "1":
    Path(output).write_bytes(b"partial-dump")
    sys.exit(9)
Path(output).write_bytes(("synthetic-dump:" + os.environ["SG_TEST_MARKER"]).encode())
""",
    )
    _program(
        executables,
        "age",
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys
if os.getenv("SG_TEST_AGE_FAIL") == "1":
    sys.stdout.buffer.write(b"partial-ciphertext")
    sys.exit(7)
if os.getenv("SG_TEST_AGE_EMPTY") == "1":
    sys.exit(0)
sys.stdout.buffer.write(b"synthetic-encrypted:" + Path(sys.argv[-1]).read_bytes())
""",
    )
    environment = os.environ.copy()
    for name in (
        "BACKUP_AGE_RECIPIENT", "BACKUP_ALLOW_PLAINTEXT",
        "SG_TEST_DUMP_FAIL", "SG_TEST_AGE_FAIL", "SG_TEST_AGE_EMPTY",
    ):
        environment.pop(name, None)
    environment.update({
        "PATH": f"{executables}{os.pathsep}{os.environ['PATH']}",
        "DATABASE_URL": "synthetic://no-real-database",
        "SG_TEST_MARKER": "first",
    })
    return environment


def _run(tmp_path: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )


def _receipt(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines())


@pytest.mark.parametrize("encrypted", [False, True])
def test_same_second_backups_remain_distinct_and_checksummed(tmp_path: Path, encrypted: bool) -> None:
    environment = _synthetic_environment(tmp_path)
    if encrypted:
        environment["BACKUP_AGE_RECIPIENT"] = "age1-synthetic-never-used"
    else:
        environment["BACKUP_ALLOW_PLAINTEXT"] = "true"

    receipts = []
    for marker in ("first", "second"):
        environment["SG_TEST_MARKER"] = marker
        process = _run(tmp_path, environment)
        assert process.returncode == 0, process.stderr
        receipt = _receipt(process.stdout)
        assert receipt["encrypted"] == str(encrypted).lower()
        artifact = tmp_path / receipt["backup"]
        manifest = tmp_path / receipt["checksum"]
        assert artifact.exists()
        assert manifest.exists()
        assert receipt["checksum"] == receipt["backup"] + ".sha256"
        expected = b"synthetic-dump:" + marker.encode()
        if encrypted:
            expected = b"synthetic-encrypted:" + expected
            assert artifact.name.endswith(".dump.age")
        else:
            assert artifact.name.endswith(".dump")
        assert artifact.read_bytes() == expected
        digest = hashlib.sha256(expected).hexdigest()
        assert manifest.read_text(encoding="utf-8") == (
            f"{digest}  {receipt['backup']}\n"
        )
        receipts.append((artifact, manifest, expected))
    assert receipts[0][0] != receipts[1][0]
    assert receipts[0][1] != receipts[1][1]
    assert receipts[0][0].read_bytes() == receipts[0][2]
    assert receipts[0][1].exists()


@pytest.mark.parametrize(
    "extra",
    [
        {"SG_TEST_DUMP_FAIL": "1", "BACKUP_ALLOW_PLAINTEXT": "true"},
        {"SG_TEST_AGE_FAIL": "1", "BACKUP_AGE_RECIPIENT": "age1-synthetic"},
        {"SG_TEST_AGE_EMPTY": "1", "BACKUP_AGE_RECIPIENT": "age1-synthetic"},
        {},
    ],
)
def test_failure_never_leaves_backup_or_success_receipt(
    tmp_path: Path, extra: dict[str, str]
) -> None:
    environment = _synthetic_environment(tmp_path)
    environment.update(extra)
    result = _run(tmp_path, environment)
    assert result.returncode != 0
    assert "backup=" not in result.stdout
    backup_dir = tmp_path / "backups"
    assert backup_dir.exists()
    assert list(backup_dir.iterdir()) == [], result.stderr
