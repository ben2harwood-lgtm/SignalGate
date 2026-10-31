#!/usr/bin/env python3
"""Verify the SignalGate audit hash chain against DATABASE_URL.

A zero-row chain can be internally consistent but is not evidence that any
operational audit history has been retained. Keep that distinction explicit
in the operator-facing CLI without changing the admin API's chain semantics.
"""
from __future__ import annotations

import json
import sys

from app import crud
from app.database import SessionLocal


def _nonempty_chain_verified(result: dict) -> bool:
    """Require a real verified head before granting the CLI a green exit."""
    count = result.get("count")
    head_hash = result.get("head_hash")
    return (
        result.get("valid") is True
        and type(count) is int
        and count > 0
        and isinstance(head_hash, str)
        and len(head_hash) == 64
        and all(char in "0123456789abcdef" for char in head_hash)
    )


def main() -> int:
    db = SessionLocal()
    try:
        result = dict(crud.verify_audit_chain(db))
    finally:
        db.close()

    # An empty chain (or a missing head) is not an affirmative audit receipt,
    # even though verifying zero records is vacuously valid mathematically.
    nonempty_verified = _nonempty_chain_verified(result)
    result["nonempty_chain_verified"] = nonempty_verified
    print(json.dumps(result, indent=2))

    if result.get("valid") is not True:
        return 1
    if not nonempty_verified:
        print(
            "Audit-chain proof is inconclusive: no verified nonempty history "
            "and 64-character chain head. Do not use as acceptance evidence.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
