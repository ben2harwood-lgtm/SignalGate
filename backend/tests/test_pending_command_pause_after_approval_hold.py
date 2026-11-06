"""Known HOLD: an approved command must not cross a later admin pause.

Synthetic TestClient regression only: no MT5, broker, paid provider, customer
data, or network integration. The strict XFAIL documents an existing guard gap;
do not remove it until the implementation is independently reviewed and
tested against real two-session PostgreSQL pause/claim ordering.
"""
from __future__ import annotations

import pytest

from .conftest import ADMIN_HEADERS, EA_HEADERS, create_signal, register_user


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "HOLD: an approved PENDING command is still claimed by /commands/pending "
        "after the global admin pause; independent PostgreSQL proof required"
    ),
)
def test_pending_command_is_not_delivered_after_admin_pause(client):
    """A pause after YES, but before the EA poll, should deny new delivery."""
    user = register_user(client, "990001")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200
    assert approved.json()["result"] == "APPROVED"

    paused = client.post("/admin/pause", headers=ADMIN_HEADERS)
    assert paused.status_code == 200

    # This is deliberately the LAST assertion: the current implementation
    # returns the already-approved command without checking the later pause.
    # Keep strict XFAIL until paused command delivery fails closed on SQLite
    # and transactionally under an actual PostgreSQL pause/claim race.
    polled = client.get(
        "/commands/pending",
        params={"user_id": user["id"]},
        headers=EA_HEADERS,
    )
    assert polled.status_code == 200
    assert polled.json()["command"] is None
