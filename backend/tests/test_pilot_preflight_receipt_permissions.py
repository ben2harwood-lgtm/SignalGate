"""Preflight evidence files must remain owner-only even with a permissive umask."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/pilot_preflight.py"
spec = importlib.util.spec_from_file_location("pilot_preflight_private_receipts", SOURCE)
preflight = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(preflight)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits are required")
def test_preflight_receipt_files_are_private_under_permissive_umask(tmp_path):
    receipt = {
        "result": "PASS",
        "backend_origin": "https://pilot.example.invalid",
        "provider_id": "PROVIDER-TEST",
        "declared_candidate_sha": "a" * 40,
        "checks": [{"name": "demo_only_mode", "passed": True, "detail": "demo"}],
    }
    previous_umask = os.umask(0)
    try:
        folder = preflight.write_receipt(receipt, tmp_path / "evidence")
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "receipt.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((folder / "receipt.md").stat().st_mode) == 0o600
    assert json.loads((folder / "receipt.json").read_text()) == receipt
    assert "**PASS**" in (folder / "receipt.md").read_text()


def test_preflight_private_receipt_write_does_not_overwrite_existing_file(tmp_path):
    target = tmp_path / "receipt.json"
    target.write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(FileExistsError):
        preflight._write_receipt_owner_only(target, "new contents")
    assert target.read_text(encoding="utf-8") == "do not overwrite"
