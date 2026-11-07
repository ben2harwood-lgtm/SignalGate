"""RELEASE HOLD: an already-approved provider command must not cross revocation.

Offline, fabricated TestClient/ORM data only. No Telegram messages, broker,
MT5, orders, external services, provider data, or execution are used. These
strict XFAIL witnesses demonstrate a known unsafe poll path; they do NOT
establish a repaired control or external acceptance.

The existing execution/pause owner must define revocation/reactivation
semantics, add two-session PostgreSQL commit-order tests, independently review
the repair, and remove each marker only when the control passes normally.
"""
from __future__ import annotations

import pytest

from app import crud, models

from .conftest import EA_HEADERS, register_user
from .test_provider_export import VALID, _headers, _provider


class _RevokedApprovedCommandDelivered(AssertionError):
    """A pending provider command crossed a committed eligibility revocation."""


@pytest.mark.parametrize(
    "revoked_scope",
    (
        "provider_paused",
        "feed_paused",
        "provider_inactive",
        "feed_inactive",
        "subscription_inactive",
        "account_inactive",
    ),
)
@pytest.mark.xfail(
    strict=True,
    raises=_RevokedApprovedCommandDelivered,
    reason=(
        "RELEASE HOLD: EA pending-claim does not recheck committed provider/feed "
        "pause or ACTIVE state, subscriber membership, or trading-account status"
    ),
)
def test_approved_provider_command_not_delivered_after_revocation(
    client, db, revoked_scope
):
    """Approve while eligible, commit one revocation, then poll the same EA.

    The approval is a positive control: no test is credited if it fails to
    create a real PENDING command in the isolated database first. An unknown
    response, broken fixture, or execution side effect must fail CI rather
    than disappear under the narrow expected-failure exception.
    """
    provider, feed, raw_key = _provider(db, f"post-approve-{revoked_scope}")
    user = register_user(
        client, "990090", f"synthetic_{revoked_scope}", "Synthetic Subscriber"
    )
    subscription, account = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, user["id"])
    )
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider, raw_key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    assert created.json()["parser_status"] == "VALID"
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED", approved.text
    command_id = approved.json()["command_id"]

    # Mutate a control *after* the explicit YES, and commit before the
    # independent HTTP poll. This is not a concurrent-transaction test.
    if revoked_scope == "provider_paused":
        provider.paused = True
        target, field, expected = provider, "paused", True
    elif revoked_scope == "feed_paused":
        feed.paused = True
        target, field, expected = feed, "paused", True
    elif revoked_scope == "provider_inactive":
        provider.status = "INACTIVE"
        target, field, expected = provider, "status", "INACTIVE"
    elif revoked_scope == "feed_inactive":
        feed.status = "INACTIVE"
        target, field, expected = feed, "status", "INACTIVE"
    elif revoked_scope == "subscription_inactive":
        subscription.status = "INACTIVE"
        target, field, expected = subscription, "status", "INACTIVE"
    else:
        account.status = "INACTIVE"
        target, field, expected = account, "status", "INACTIVE"

    db.commit()
    db.expire_all()
    assert getattr(db.get(type(target), target.id), field) == expected
    with db.no_autoflush:
        assert db.get(models.Command, command_id).status == "PENDING"

    # End the fixture's read transaction before the separate client session,
    # avoiding false SQLite read-lock interactions in the offline matrix.
    db.rollback()
    polled = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": user["id"]},
    )
    assert polled.status_code == 200, polled.text
    assert "command" in polled.json()

    db.expire_all()
    command = db.get(models.Command, command_id)
    assert command is not None
    sent_audits = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count()
    )
    executions = db.query(models.Execution).count()
    assert executions == 0, "Unexpected execution side effect in broker-free test"

    delivered = polled.json()["command"]
    if delivered is not None:
        assert delivered["command_id"] == command_id
        assert command.status == "SENT_TO_EA"
        assert sent_audits == 1
        raise _RevokedApprovedCommandDelivered(
            f"EA was issued {command_id} after committed {revoked_scope}"
        )

    # Becomes a normal passing safety requirement only after the owner fix.
    assert command.status == "PENDING"
    assert sent_audits == 0
