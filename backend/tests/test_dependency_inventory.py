"""Candidate-bound inventory is evidence, not proof of dependency installation."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "generate_dependency_inventory.py"
SPEC = importlib.util.spec_from_file_location("generate_dependency_inventory", SOURCE)
assert SPEC and SPEC.loader
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _committed_source(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    for name in inventory.SOURCE_FILES:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic tracked input\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=Source Test", "-c", "user.email=source@test.invalid",
         "add", *inventory.SOURCE_FILES)
    _git(repo, "-c", "user.name=Source Test", "-c", "user.email=source@test.invalid",
         "commit", "-qm", "synthetic candidate")
    return repo


def test_provenance_binds_only_verified_tracked_inputs_and_never_claims_env_match(tmp_path):
    repo = _committed_source(tmp_path)
    result = inventory.candidate_source_provenance(repo)
    assert result["candidate_commit"] == _git(repo, "rev-parse", "HEAD")
    assert result["tracked_inputs_match_candidate"] is True
    assert result["installed_environment_match_status"] == "NOT_VERIFIED"
    assert set(result["source_input_sha256"]) == set(inventory.SOURCE_FILES)


@pytest.mark.parametrize("relative", inventory.SOURCE_FILES)
def test_provenance_rejects_mutated_tracked_input(tmp_path, relative):
    repo = _committed_source(tmp_path)
    (repo / relative).write_text("changed after commit\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from candidate Git blob"):
        inventory.candidate_source_provenance(repo)


def test_provenance_refuses_missing_tracked_source(tmp_path):
    repo = _committed_source(tmp_path)
    (repo / inventory.SOURCE_FILES[0]).unlink()
    with pytest.raises(ValueError, match="not a regular working file"):
        inventory.candidate_source_provenance(repo)


def test_receipts_are_private_no_clobber_and_preserve_evidence(tmp_path):
    path = tmp_path / "inventory.json"
    inventory.write_new_receipt(path, {"scope": "synthetic"})
    assert json.loads(path.read_text()) == {"scope": "synthetic"}
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        inventory.write_new_receipt(path, {"scope": "replacement"})
    assert json.loads(path.read_text()) == {"scope": "synthetic"}


def test_receipt_never_follows_existing_symlink(tmp_path):
    victim = tmp_path / "victim.json"
    victim.write_text("unchanged", encoding="utf-8")
    link = tmp_path / "inventory.json"
    try:
        link.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unsupported on this filesystem")
    with pytest.raises(FileExistsError):
        inventory.write_new_receipt(link, {"scope": "replacement"})
    assert victim.read_text() == "unchanged"


def test_provenance_rejects_matching_bytes_from_uncommitted_symlink(tmp_path):
    repo = _committed_source(tmp_path)
    source = repo / inventory.SOURCE_FILES[0]
    replacement = tmp_path / "same-contents.txt"
    replacement.write_bytes(source.read_bytes())
    source.unlink()
    try:
        source.symlink_to(replacement)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unsupported on this filesystem")
    with pytest.raises(ValueError, match="not a regular working file"):
        inventory.candidate_source_provenance(repo)
