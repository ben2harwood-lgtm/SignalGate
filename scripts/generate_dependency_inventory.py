#!/usr/bin/env python3
"""Inventory installed Python packages, with explicit candidate-source provenance.

This is local environment evidence, NOT proof that the candidate was deployed or
that the installed packages match all pinned requirements. No network calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE_FILES = (
    "scripts/generate_dependency_inventory.py",
    "backend/requirements.txt",
    "backend/requirements-hosted.txt",
    "telegram_bot/requirements.txt",
)


def license_text(dist: metadata.Distribution) -> str | None:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    value = meta.get("License")
    if value and value.strip() and value.strip().upper() != "UNKNOWN":
        return value.strip()
    classifiers = meta.get_all("Classifier") or []
    licences = [
        item.split("License ::", 1)[1].strip()
        for item in classifiers
        if "License ::" in item
    ]
    return "; ".join(licences) or None


def candidate_source_provenance(repo_root: Path) -> dict:
    """Refuse dirty/missing source inputs instead of mislabelling their revision."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected an exact SHA-1 Git candidate commit")

    fingerprints = {}
    for relative in SOURCE_FILES:
        original = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{commit}:{relative}"],
            check=True, capture_output=True,
        ).stdout
        source = repo_root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Source input is not a regular working file: {relative}")
        working = source.read_bytes()
        if working != original:
            raise ValueError(f"Source file differs from candidate Git blob: {relative}")
        fingerprints[relative] = hashlib.sha256(original).hexdigest()
    return {
        "candidate_commit": commit,
        "tracked_inputs_match_candidate": True,
        "source_input_sha256": fingerprints,
        "installed_environment_match_status": "NOT_VERIFIED",
    }


def installed_packages() -> list[dict]:
    packages = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or dist.name
        if name:
            packages.append({
                "name": name,
                "version": dist.version,
                "license": license_text(dist),
                "homepage": dist.metadata.get("Home-page"),
            })
    return sorted(packages, key=lambda row: (row["name"].lower(), row["version"]))


def write_new_receipt(path: Path, payload: dict) -> None:
    """Publish only fully written JSON, atomically and without overwriting."""
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        # A hard-link is a no-replace atomic publish on the same filesystem.
        # os.replace/os.rename would silently overwrite an older receipt.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dependency-inventory.json", type=Path)
    args = parser.parse_args()
    try:
        provenance = candidate_source_provenance(Path(__file__).resolve().parents[1])
        packages = installed_packages()
        payload = {
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "format": "SignalGate installed dependency inventory v2",
            "scope": "observed_installed_python_environment_only",
            **provenance,
            "package_count": len(packages),
            "packages": packages,
        }
        write_new_receipt(args.output, payload)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"Inventory not written ({exc.__class__.__name__}); check source and output.\n")
    print(f"wrote {args.output} ({len(packages)} observed installed packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
