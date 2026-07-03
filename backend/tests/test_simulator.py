"""End-to-end simulator test: create -> approve -> simulate full lifecycle.

Drives the EA simulator against the FastAPI TestClient (no MT5, no network).
"""
from __future__ import annotations

import os
import sys

# Make the simulator package importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SIM = os.path.join(_HERE, "..", "..", "simulator")
sys.path.insert(0, os.path.abspath(_SIM))

from ea_simulator import EASimulator  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402

from .conftest import EA_HEADERS, create_signal, register_user  # noqa: E402

VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _command_status(command_id):
    db = SessionLocal()
    try:
        return db.get(models.Command, command_id).status
    finally:
        db.close()


def _ledger_status(signal_id):
    db = SessionLocal()
    try:
        return (
            db.query(models.PerformanceLedger)
            .filter(models.PerformanceLedger.signal_id == signal_id)
            .first()
            .result_status
        )
    finally:
        db.close()


def test_full_simulator_flow(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    approve = client.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"}
    ).json()
    assert approve["result"] == "APPROVED"

    sim = EASimulator(
        http=client,
        user_id=user["id"],
        api_key="test-ea-key",
        delay=0,
        verbose=False,
    )
    processed = sim.run_once()
    assert processed is True

    cid = approve["command_id"]
    assert _command_status(cid) == "FULLY_CLOSED"

    # Management events recorded.
    db = SessionLocal()
    try:
        events = (
            db.query(models.TradeManagementEvent)
            .filter(models.TradeManagementEvent.command_id == cid)
            .count()
        )
    finally:
        db.close()
    assert events >= 6

    # Ledger reflects a TP outcome.
    assert _ledger_status(sig["id"]) in {"TP3_HIT", "TP2_HIT", "TP1_HIT"}


def test_simulator_local_idempotency(client):
    user = register_user(client, "123")
    sig = create_signal(client, VALID)
    client.post(f"/signals/{sig['id']}/approve", json={"telegram_user_id": "123"})

    sim = EASimulator(http=client, user_id=user["id"], api_key="test-ea-key",
                      delay=0, verbose=False)
    assert sim.run_once() is True
    # No more pending commands; second run finds nothing.
    assert sim.run_once() is False
