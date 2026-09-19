"""Static safety contract for the Windows MetaEditor evidence harness."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "capture_mt5_compile_evidence.ps1"
WRAPPER = ROOT / "scripts" / "Run-MT5-Compile-Acceptance.bat"
ACCEPTANCE = ROOT / "docs" / "MT5_ACCEPTANCE.md"
SETUP = ROOT / "mt5_ea" / "README_MT5_SETUP.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_harness_binds_compile_to_exact_frozen_candidate():
    text = _text(HARNESS)
    assert "CandidateRef" in text
    assert "CandidateSha" in text
    assert 'rev-parse "$CandidateRef^{commit}"' in text
    assert "does not match the expected SHA" in text or "not expected CandidateSha" in text
    assert "worktree add --detach" in text
    assert "worktreeHead -ne $CandidateSha" in text
    assert 'Join-Path $candidateWorktree "mt5_ea\\SignalGateEA.mq5"' in text


def test_harness_records_source_and_tool_versions():
    text = _text(HARNESS)
    assert "Get-FileHash" in text
    assert "ea_source_sha256" in text
    assert "metaeditor_file_version" in text
    assert "terminal_file_version" in text
    assert "harness_repository_head" in text
    assert "detached_worktree_head" in text


def test_harness_requires_zero_errors_and_zero_warnings():
    text = _text(HARNESS)
    assert "/compile:" in text
    assert "/include:" in text
    assert "'/log'" in text
    assert r"result\s+(\d+)\s+errors?,\s+(\d+)\s+warnings?" in text
    assert "$result.Errors -eq 0 -and $result.Warnings -eq 0" in text
    assert "exit 2" in text


def test_wrapper_calls_only_the_evidence_harness():
    text = _text(WRAPPER)
    assert "capture_mt5_compile_evidence.ps1" in text
    assert "powershell.exe" in text
    assert "artifacts\\mt5-acceptance" in text


def test_mt5_docs_treat_license_as_hosted_identity():
    setup = _text(SETUP)
    acceptance = _text(ACCEPTANCE)
    assert "X-SG-License-Key" in setup
    assert "Required customer identity credential in hosted mode" in setup
    assert "local-demo compatibility" in setup.lower()
    assert "detached temporary Git worktree" in acceptance
    assert "0 errors, 0 warnings" in acceptance


def test_local_mt5_evidence_directory_is_gitignored():
    gitignore = _text(ROOT / ".gitignore")
    assert "artifacts/mt5-acceptance/" in gitignore
