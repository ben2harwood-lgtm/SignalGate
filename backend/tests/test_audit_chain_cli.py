"""Operator audit CLI must not turn a missing audit trail into release proof."""
from __future__ import annotations

import json

import pytest

from app import crud, models
from app.database import SessionLocal
import scripts_verify_audit_chain as audit_cli


def _append_audit() -> None:
    with SessionLocal() as db:
        crud.add_audit(
            db,
            "AUDIT_CLI_TEST",
            "test",
            "audit-cli",
            {"synthetic": True},
        )
        db.commit()


def test_empty_chain_cli_refuses_an_affirmative_receipt(capsys):
    assert audit_cli.main() == 2
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["valid"] is True  # Core verifier's vacuous-chain semantics.
    assert receipt["count"] == 0
    assert receipt["head_hash"] is None
    assert receipt["nonempty_chain_verified"] is False
    assert "inconclusive" in output.err.lower()


def test_deleting_every_audit_row_cannot_leave_cli_green(capsys):
    _append_audit()
    with SessionLocal() as db:
        assert db.query(models.AuditLog).count() == 1
        db.query(models.AuditLog).delete(synchronize_session=False)
        db.commit()

    assert audit_cli.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["valid"] is True
    assert receipt["count"] == 0
    assert receipt["nonempty_chain_verified"] is False


def test_valid_nonempty_history_returns_a_head_and_green_exit(capsys):
    _append_audit()

    assert audit_cli.main() == 0
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["valid"] is True
    assert receipt["count"] == 1
    assert len(receipt["head_hash"]) == 64
    assert receipt["nonempty_chain_verified"] is True
    assert output.err == ""


def test_tampered_nonempty_history_remains_red(capsys):
    _append_audit()
    with SessionLocal() as db:
        row = db.query(models.AuditLog).first()
        row.payload_json = '{"tampered": true}'
        db.commit()

    assert audit_cli.main() == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["valid"] is False
    assert receipt["nonempty_chain_verified"] is False
    assert receipt["broken_id"] is not None


@pytest.mark.parametrize(
    "receipt",
    [
        {"valid": True, "count": 1, "head_hash": None},
        {"valid": True, "count": 1, "head_hash": "not-a-sha256"},
        {"valid": True, "count": True, "head_hash": "a" * 64},
        {"valid": True, "count": -1, "head_hash": "a" * 64},
        {"valid": False, "count": 1, "head_hash": "a" * 64},
    ],
)
def test_inconsistent_summary_cannot_be_treated_as_verified(receipt):
    assert audit_cli._nonempty_chain_verified(receipt) is False
