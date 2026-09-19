"""Acceptance-bundle safety and determinism tests."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_acceptance_bundle.py"
SPEC = importlib.util.spec_from_file_location("build_acceptance_bundle", SCRIPT)
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)

SHA = "a" * 40


def test_all_configured_profile_files_exist():
    for profile, paths in bundle.PROFILES.items():
        assert paths, profile
        for relative in paths:
            assert (ROOT / relative).is_file(), f"{profile}: missing {relative}"


def test_bundle_is_deterministic_and_manifested(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "b.txt").write_text("beta\n", encoding="utf-8")

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    paths = ("nested/b.txt", "a.txt")
    m1 = bundle.build_bundle(
        repo_root=root,
        output_path=first,
        candidate_sha=SHA,
        profile="test",
        verify_source=False,
        paths=paths,
    )
    m2 = bundle.build_bundle(
        repo_root=root,
        output_path=second,
        candidate_sha=SHA,
        profile="test",
        verify_source=False,
        paths=reversed(paths),
    )

    assert first.read_bytes() == second.read_bytes()
    assert m1 == m2
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["MANIFEST.json", "a.txt", "nested/b.txt"]
        stored = json.loads(archive.read("MANIFEST.json"))
        assert stored == m1
        assert stored["candidate_sha"] == SHA


@pytest.mark.parametrize("bad", ["abc", "A" * 40, "g" * 40, "../" + "a" * 40])
def test_candidate_sha_must_be_exact_lowercase_hex(tmp_path, bad):
    with pytest.raises(ValueError):
        bundle.build_bundle(
            repo_root=tmp_path,
            output_path=tmp_path / "x.zip",
            candidate_sha=bad,
            profile="test",
            paths=(),
        )


@pytest.mark.parametrize("path", [".env", "../secret", "/tmp/secret", "x/.env.hosted"])
def test_bundle_rejects_unsafe_or_environment_paths(tmp_path, path):
    with pytest.raises(ValueError):
        bundle.build_bundle(
            repo_root=tmp_path,
            output_path=tmp_path / "x.zip",
            candidate_sha=SHA,
            profile="test",
            paths=(path,),
        )


def test_missing_allowlisted_file_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        bundle.build_bundle(
            repo_root=tmp_path,
            output_path=tmp_path / "x.zip",
            candidate_sha=SHA,
            profile="test",
            paths=("missing.txt",),
        )


def test_verified_source_requires_matching_git_head(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "SignalGate CI"], cwd=root, check=True)
    subprocess.run(["git", "add", "a.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()

    output = tmp_path / "verified.zip"
    manifest = bundle.build_bundle(
        repo_root=root,
        output_path=output,
        candidate_sha=head,
        profile="test",
        paths=("a.txt",),
    )
    assert manifest["source_tree_verified"] is True
    assert manifest["source_head"] == head

    with pytest.raises(ValueError, match="does not match repo HEAD"):
        bundle.build_bundle(
            repo_root=root,
            output_path=tmp_path / "wrong.zip",
            candidate_sha="b" * 40,
            profile="test",
            paths=("a.txt",),
        )


def test_unverified_source_is_explicitly_marked(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    manifest = bundle.build_bundle(
        repo_root=tmp_path,
        output_path=tmp_path / "unverified.zip",
        candidate_sha=SHA,
        profile="test",
        paths=("a.txt",),
        verify_source=False,
    )
    assert manifest["source_tree_verified"] is False
    assert manifest["source_head"] is None
