"""An unrelated or stale checksum manifest must not authorise a restore."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

RESTORE = Path(__file__).resolve().parents[2] / "scripts/restore_postgres.sh"


def exercise(tmp_path, *, mismatch: str) -> tuple[subprocess.CompletedProcess, bool]:
    backup = tmp_path / "selected backup.dump"
    other = tmp_path / "unrelated.dump"
    backup.write_bytes(b"selected-synthetic-backup")
    other.write_bytes(b"different-synthetic-backup")
    def record(path):
        return hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path) + "\n"
    manifest = backup.with_name(backup.name + ".sha256")
    if mismatch == "other_file":
        manifest.write_text(record(other))
    elif mismatch == "changed_target":
        manifest.write_text(record(backup))
        backup.write_bytes(b"mutated-after-manifest")
    elif mismatch == "multiple_records":
        manifest.write_text(record(backup) + record(other))
    elif mismatch == "missing_target":
        manifest.write_text(record(backup))
        backup.unlink()
    elif mismatch == "empty_manifest":
        manifest.write_text("")
    else:
        assert mismatch == "valid"
        manifest.write_text(record(backup))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_restore = bin_dir / "pg_restore"
    fake_restore.write_text(
        "#!/bin/sh\nprintf 'invoked' > \"$SG_RESTORE_MARKER\"\n",
        encoding="utf-8",
    )
    fake_restore.chmod(0o755)
    marker = tmp_path / "restore-invoked"
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
        "RESTORE_DATABASE_URL": "postgresql://127.0.0.1/synthetic",
        "BACKUP_FILE": str(backup),
        "BACKUP_ALLOW_PLAINTEXT_RESTORE": "true",
        "SG_RESTORE_MARKER": str(marker),
    }
    result = subprocess.run(
        ["bash", str(RESTORE)], env=env,
        capture_output=True, text=True, timeout=10,
    )
    return result, marker.exists()


@pytest.mark.parametrize("mismatch", ["other_file", "changed_target", "multiple_records", "missing_target", "empty_manifest"])
def test_mismatched_checksum_manifest_never_invokes_restore(tmp_path, mismatch):
    result, invoked = exercise(tmp_path, mismatch=mismatch)
    assert result.returncode != 0
    assert not invoked
    assert "refusing restore" in result.stderr


def test_valid_checksum_manifest_invokes_only_stub_restore(tmp_path):
    result, invoked = exercise(tmp_path, mismatch="valid")
    assert result.returncode == 0, result.stderr
    assert invoked
    assert "restore_completed=" in result.stdout
