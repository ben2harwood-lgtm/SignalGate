"""Public-source guard: local dotenv variants and evidence stay out of Git/Docker.

This is defence in depth, not a substitute for reviewing staged diffs or
Git-history secret scanning: ``git add -f`` can override ignore rules.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ignore_repo(tmp_path):
    """Exercise the checked-in .gitignore with Git's real matching semantics."""
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    return tmp_path


def git_ignores(repo: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", relative_path],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.parametrize("relative_path", [
    ".env", ".env.local", ".env.production",
    "backend/.env", "backend/.env.staging", "telegram_bot/.env.private",
    "artifacts/new-provider/acceptance-receipt.json",
    "artifacts/mt5-acceptance/compiler-log.txt",
])
def test_local_secret_or_receipt_is_ignored(ignore_repo, relative_path):
    assert git_ignores(ignore_repo, relative_path), relative_path


@pytest.mark.parametrize("relative_path", [
    ".env.example", ".env.hosted.example", "backend/.env.example",
    "docs/evidence/README.md",
])
def test_safe_templates_remain_trackable(ignore_repo, relative_path):
    assert not git_ignores(ignore_repo, relative_path), relative_path


def test_docker_context_has_nested_dotenv_and_artifact_exclusions():
    # Static contract only: the hosted container job separately builds the image.
    rules = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "**/.env" in rules
    assert "**/.env.*" in rules
    assert "artifacts/" in rules
