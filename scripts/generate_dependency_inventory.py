#!/usr/bin/env python3
"""Generate a machine-readable installed dependency/licence inventory."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata as metadata
import json
from pathlib import Path


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dependency-inventory.json")
    args = parser.parse_args()

    packages = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or dist.name
        if not name:
            continue
        packages.append(
            {
                "name": name,
                "version": dist.version,
                "license": license_text(dist),
                "homepage": dist.metadata.get("Home-page"),
            }
        )
    packages.sort(key=lambda row: row["name"].lower())
    payload = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "format": "SignalGate installed dependency inventory v1",
        "package_count": len(packages),
        "packages": packages,
    }
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({len(packages)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
