"""An unrelated or stale checksum manifest must not authorise a restore."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import threading
import time

import pytest

RESTORE = Path(__file__).resolve().parents[2] / "scripts/restore_postgres.sh"

@pytest.fixture(autouse=True)
def _mock_readonly_target_probe(tmp_path, monkeypatch):
    """Keep every restore regression offline; never contact a real database."""
    probe_bin = tmp_path / "readonly-psql-probe"
    probe_bin.mkdir()
    psql_stub = probe_bin / "psql"
    psql_stub.write_text(
        "#!/bin/sh\n"
        "case \"${SG_PSQL_RESPONSE:-empty}\" in\n"
        "  empty) printf 'f\\n' ;;\n"
        "  occupied) printf 't\\n' ;;\n"
        "  malformed) printf 'unknown\\n' ;;\n"
        "  failure) exit 7 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    psql_stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(probe_bin) + os.pathsep + os.environ.get("PATH", ""))



def exercise(tmp_path, *, mismatch: str, psql_response: str = "empty", same_target: bool = False) -> tuple[subprocess.CompletedProcess, bool]:
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
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SG_RESTORE_ARGS\"\n"
        "printf 'invoked' > \"$SG_RESTORE_MARKER\"\n",
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
        "SG_RESTORE_ARGS": str(tmp_path / "restore-args"),
        "SG_PSQL_RESPONSE": psql_response,
    }
    if same_target:
        env["DATABASE_URL"] = env["RESTORE_DATABASE_URL"]
    else:
        env.pop("DATABASE_URL", None)
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


@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_restore_rejects_nonregular_or_symlinked_backup(tmp_path, kind):
    backup = tmp_path / "nonregular.dump"
    if kind == "fifo":
        os.mkfifo(backup)
    else:
        target = tmp_path / "underlying.dump"
        target.write_bytes(b"synthetic")
        backup.symlink_to(target)
    (tmp_path / "nonregular.dump.sha256").write_text(
        hashlib.sha256(b"synthetic").hexdigest() + "  " + str(backup) + "\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "restore-invoked"
    shim = bin_dir / "pg_restore"
    shim.write_text('#!/bin/sh\ntouch "$SG_RESTORE_MARKER"\n')
    shim.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "RESTORE_DATABASE_URL": "postgresql://127.0.0.1/synthetic",
           "BACKUP_FILE": str(backup), "BACKUP_ALLOW_PLAINTEXT_RESTORE": "true",
           "SG_RESTORE_MARKER": str(marker)}
    result = subprocess.run(["bash", str(RESTORE)], env=env, capture_output=True,
                            text=True, timeout=5)
    assert result.returncode != 0
    assert "refusing restore" in result.stderr
    assert not marker.exists()


def test_restore_reads_only_checksum_verified_snapshot(tmp_path):
    """Real cmp passes, then the original backup changes before pg_restore."""
    backup = tmp_path / "selected backup.dump"
    initial = b"synthetic-before-compare\n"
    later = b"synthetic-after-compare\n"
    backup.write_bytes(initial)
    (tmp_path / "selected backup.dump.sha256").write_text(
        hashlib.sha256(initial).hexdigest() + "  " + str(backup) + "\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    passed = tmp_path / "cmp-passed"
    release = tmp_path / "cmp-release"
    captured = tmp_path / "restored-input.bin"
    cmp_shim = bin_dir / "cmp"
    # The timing shim delegates the actual comparison to system cmp.
    cmp_shim.write_text(
        '#!/bin/bash\n/usr/bin/cmp "$@"\nstatus=$?\n'
        'if [ "$status" -eq 0 ]; then\n  touch "$SG_CMP_PASSED"\n'
        '  for ((i=0;i<1000;i++)); do [ -e "$SG_CMP_RELEASE" ] && break; sleep .005; done\n'
        'fi\nexit "$status"\n'
    )
    cmp_shim.chmod(0o755)
    restore = bin_dir / "pg_restore"
    restore.write_text(
        '#!/bin/bash\nfor last; do :; done\ncat -- "$last" > "$SG_CAPTURE"\n'
    )
    restore.chmod(0o755)
    events = []
    def mutate_after_valid_cmp():
        try:
            for _ in range(1000):
                if passed.exists():
                    break
                time.sleep(0.005)
            if not passed.exists():
                events.append("barrier_not_reached")
                return
            backup.write_bytes(later)
            events.append("mutated")
        finally:
            release.touch()
    worker = threading.Thread(target=mutate_after_valid_cmp, daemon=True)
    worker.start()
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "RESTORE_DATABASE_URL": "postgresql://127.0.0.1/synthetic",
           "BACKUP_FILE": str(backup), "BACKUP_ALLOW_PLAINTEXT_RESTORE": "true",
           "SG_CMP_PASSED": str(passed), "SG_CMP_RELEASE": str(release),
           "SG_CAPTURE": str(captured)}
    result = subprocess.run(["bash", str(RESTORE)], env=env,
                            capture_output=True, text=True, timeout=12)
    worker.join(timeout=2)
    assert events == ["mutated"]
    assert result.returncode == 0, result.stderr
    assert backup.read_bytes() == later
    assert captured.read_bytes() == initial


@pytest.mark.parametrize("response", ("occupied", "failure", "malformed"))
def test_restore_refuses_nonempty_or_unverifiable_destination(tmp_path, response):
    result, invoked = exercise(tmp_path, mismatch="valid", psql_response=response)
    assert result.returncode != 0
    assert not invoked
    assert "refusing restore" in result.stderr
    assert "synthetic" not in result.stderr


def test_restore_refuses_identical_source_and_destination_url(tmp_path):
    result, invoked = exercise(tmp_path, mismatch="valid", same_target=True)
    assert result.returncode != 0
    assert not invoked
    assert "refusing restore" in result.stderr


def test_empty_target_restore_never_uses_destructive_clean_flags(tmp_path):
    result, invoked = exercise(tmp_path, mismatch="valid")
    assert result.returncode == 0, result.stderr
    assert invoked
    args = (tmp_path / "restore-args").read_text()
    assert "--exit-on-error" in args
    assert "--clean" not in args
    assert "--if-exists" not in args
    assert "--dbname=postgresql://127.0.0.1/synthetic" in args
