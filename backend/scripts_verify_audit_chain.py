#!/usr/bin/env python3
"""Verify the SignalGate audit hash chain against DATABASE_URL."""
from __future__ import annotations

import json

from app import crud
from app.database import SessionLocal


def main() -> int:
    db = SessionLocal()
    try:
        result = crud.verify_audit_chain(db)
    finally:
        db.close()
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
