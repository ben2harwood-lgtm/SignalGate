#!/usr/bin/env python3
"""Build deterministic, allowlisted SignalGate external-review bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

COMMON = (
    "SIGNALGATE-STATUS.md",
    "docs/RELEASE_CANDIDATE_2026-09-19.md",
    "docs/ACCEPTANCE_EVIDENCE_INDEX.md",
)

PROFILES: dict[str, tuple[str, ...]] = {
    "mt5": COMMON
    + (
        "mt5_ea/SignalGateEA.mq5",
        "mt5_ea/README_MT5_SETUP.md",
        "docs/MT5_ACCEPTANCE.md",
        "docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md",
    ),
    "security": COMMON
    + (
        "docs/ARCHITECTURE.md",
        "docs/SECURITY_OVERVIEW.md",
        "docs/THREAT_MODEL.md",
        "docs/PRIVACY_DATA_MAP.md",
        "docs/INCIDENT_RUNBOOKS.md",
        "docs/PENTEST_SCOPE.md",
        "docs/evidence/SECURITY_REVIEW_RECEIPT_TEMPLATE.md",
    ),
    "counsel": COMMON
    + (
        "docs/ARCHITECTURE.md",
        "docs/PRIVACY_DATA_MAP.md",
        "docs/PROVIDER_EDITION.md",
        "docs/COMMERCIAL_OFFER.md",
        "docs/REGULATORY_COUNSEL_BRIEF.md",
        "docs/REGULATORY_GATE.md",
        "docs/evidence/REGULATORY_PRIVACY_RECEIPT_TEMPLATE.md",
    ),
    "pilot": COMMON
    + (
        "docs/BETA_ACCEPTANCE.md",
        "docs/CONTROLLED_PROVIDER_PILOT.md",
        "docs/FIRST_PROVIDER_RUNBOOK.md",
        "docs/PROVIDER_ONBOARDING.md",
        "docs/PROVIDER_TELEGRAM_SOURCE.md",
        "docs/DEMO_SCRIPT.md",
        "docs/SECURITY_OVERVIEW.md",
        "docs/SUPPORT_SERVICE_TARGETS.md",
        "docs/evidence/PILOT_OPERATIONS_LOG_TEMPLATE.md",
        "docs/evidence/EXCEPTION_REGISTER_TEMPLATE.md",
    ),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _normalise_paths(paths: Iterable[str]) -> tuple[str, ...]:
    ordered = tuple(sorted(set(paths)))
    for raw in ordered:
        p = Path(raw)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"unsafe bundle path: {raw}")
        if raw.startswith(".env") or "/.env" in raw:
            raise ValueError(f"environment files are forbidden: {raw}")
    return ordered


def build_bundle(
    *,
    repo_root: Path,
    output_path: Path,
    candidate_sha: str,
    profile: str,
    paths: Iterable[str] | None = None,
) -> dict:
    """Build one deterministic ZIP and return its manifest."""
    candidate_sha = candidate_sha.lower()
    if not FULL_SHA_RE.fullmatch(candidate_sha):
        raise ValueError("candidate_sha must be an exact 40-character lowercase hex commit SHA")
    if profile not in PROFILES and paths is None:
        raise ValueError(f"unknown profile: {profile}")

    selected = _normalise_paths(paths if paths is not None else PROFILES[profile])
    files: list[tuple[str, bytes]] = []
    for relative in selected:
        source = repo_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"required bundle file is missing: {relative}")
        files.append((relative, source.read_bytes()))

    manifest = {
        "schema": "signalgate-acceptance-bundle-v1",
        "candidate_sha": candidate_sha,
        "profile": profile,
        "files": [
            {"path": name, "sha256": _sha256(data), "bytes": len(data)}
            for name, data in files
        ],
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8")
        + b"\n"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as archive:
        archive.writestr(_zip_info("MANIFEST.json"), manifest_bytes)
        for name, data in files:
            archive.writestr(_zip_info(name), data)

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    output = args.output or (
        args.repo_root
        / "dist"
        / f"signalgate-{args.profile}-{args.candidate_sha[:12]}.zip"
    )
    manifest = build_bundle(
        repo_root=args.repo_root.resolve(),
        output_path=output.resolve(),
        candidate_sha=args.candidate_sha,
        profile=args.profile,
    )
    print(f"bundle={output}")
    print(f"profile={manifest['profile']}")
    print(f"candidate_sha={manifest['candidate_sha']}")
    print(f"files={len(manifest['files'])}")
    print(f"sha256={_sha256(output.read_bytes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
