"""RELEASE HOLD: an already-approved provider command must not cross revocation.

Offline, fabricated TestClient/ORM data only. No Telegram messages, broker,
MT5, orders, external services, provider data, or execution are used. These
must-pass regressions verify claim-time revocation but do not establish
independent lock-order review or external acceptance.

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

    # Revoked commands must remain PENDING without a SENT audit.
    assert command.status == "PENDING"
    assert sent_audits == 0


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
def test_postapproval_revocation_keeps_other_provider_pending_poll_available(
    client, db, revoked_scope
):
    """Passing isolation control: revoking A must never disable unrelated B.

    Two independent synthetic providers, feeds, users, subscriptions and
    trading accounts have already received explicit YES approvals. The
    revocation belongs only to provider A. Poll B, not A: the separate
    must-pass witness above blocks unsafe delivery of A.

    This must stay a normal PASS when the execution owner adds the required
    fail-closed eligibility checks. A global pause-on-any-revocation repair
    would incorrectly fail this test.
    """
    provider_a, feed_a, key_a = _provider(db, f"revocation-isolation-a-{revoked_scope}")
    provider_b, feed_b, key_b = _provider(db, f"revocation-isolation-b-{revoked_scope}")
    assert provider_a.organization_id != provider_b.organization_id
    user_a = register_user(
        client, "990091", "synthetic_isolation_a", "Synthetic A"
    )
    user_b = register_user(
        client, "990092", "synthetic_isolation_b", "Synthetic B"
    )
    subscription_a, account_a = crud.subscribe_user_to_feed(
        db, provider_a, feed_a, db.get(models.User, user_a["id"])
    )
    crud.subscribe_user_to_feed(
        db, provider_b, feed_b, db.get(models.User, user_b["id"])
    )
    db.commit()

    command_ids = []
    for provider, feed, key, user in (
        (provider_a, feed_a, key_a, user_a),
        (provider_b, feed_b, key_b, user_b),
    ):
        created = client.post(
            "/signals/create",
            headers=_headers(provider, key),
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
        command_ids.append(approved.json()["command_id"])
    command_a_id, command_b_id = command_ids
    assert command_a_id != command_b_id

    if revoked_scope == "provider_paused":
        provider_a.paused = True
    elif revoked_scope == "feed_paused":
        feed_a.paused = True
    elif revoked_scope == "provider_inactive":
        provider_a.status = "INACTIVE"
    elif revoked_scope == "feed_inactive":
        feed_a.status = "INACTIVE"
    elif revoked_scope == "subscription_inactive":
        subscription_a.status = "INACTIVE"
    else:
        account_a.status = "INACTIVE"
    db.commit()
    db.expire_all()
    assert db.get(models.Command, command_a_id).status == "PENDING"
    assert db.get(models.Command, command_b_id).status == "PENDING"
    db.rollback()  # Release fixture read transaction before isolated API poll.

    polled = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": user_b["id"]},
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["command"]["command_id"] == command_b_id

    db.expire_all()
    assert db.get(models.Command, command_a_id).status == "PENDING"
    assert db.get(models.Command, command_b_id).status == "SENT_TO_EA"
    sent_counts = {
        command_id: (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
        )
        for command_id in (command_a_id, command_b_id)
    }
    assert sent_counts == {command_a_id: 0, command_b_id: 1}
    assert db.query(models.Execution).count() == 0
