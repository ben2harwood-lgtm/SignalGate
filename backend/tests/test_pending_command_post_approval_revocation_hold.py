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


class _RevokedOldestPendingStarvesActiveSibling(AssertionError):
    """An ineligible older command blocked a later, currently authorised YES."""


def test_same_subscriber_revoked_older_feed_does_not_starve_active_sibling(
    client, db
):
    """Two explicit YES commands for one user, one provider, two active feeds.

    The older feed A loses only its subscription after both approvals. The
    later feed B is still authorised on the same trading account and must be
    claimable without delivering A, mutating A or creating execution events.
    This regression requires eligible sibling liveness while the revoked
    command remains PENDING with no SENT audit or execution.
    """
    provider, feed_a, raw_key = _provider(db, "same-user-feed-starvation")
    feed_b = crud.create_feed(
        db, provider, "Active sibling feed", "same-user-sibling-source"
    )
    db.commit()  # Release audit-chain lock before HTTP registration.
    user = register_user(
        client, "990096", "synthetic_same_user_feeds", "Synthetic Subscriber"
    )
    subscription_a, account_a = crud.subscribe_user_to_feed(
        db, provider, feed_a, db.get(models.User, user["id"])
    )
    subscription_b, account_b = crud.subscribe_user_to_feed(
        db, provider, feed_b, db.get(models.User, user["id"])
    )
    db.commit()
    assert feed_a.id != feed_b.id
    assert subscription_a.id != subscription_b.id
    assert account_a.id == account_b.id
    command_ids = []
    for feed in (feed_a, feed_b):
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
        command_ids.append(approved.json()["command_id"])
    older_id, eligible_id = command_ids
    assert older_id != eligible_id

    db.expire_all()
    older = db.get(models.Command, older_id)
    eligible = db.get(models.Command, eligible_id)
    assert older.status == eligible.status == "PENDING"
    assert older.created_at < eligible.created_at
    assert older.feed_id == feed_a.id
    assert eligible.feed_id == feed_b.id
    assert older.account_id == eligible.account_id == account_a.id

    subscription_a.status = "INACTIVE"
    db.commit()
    db.expire_all()
    assert db.get(models.Subscription, subscription_a.id).status == "INACTIVE"
    assert db.get(models.Subscription, subscription_b.id).status == "ACTIVE"
    db.rollback()  # End fixture read transaction before HTTP poll.

    polled = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": user["id"]},
    )
    assert polled.status_code == 200, polled.text
    assert "command" in polled.json()

    db.expire_all()
    older = db.get(models.Command, older_id)
    eligible = db.get(models.Command, eligible_id)
    sent_audits = {
        command_id: (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
        )
        for command_id in (older_id, eligible_id)
    }
    assert older.status == "PENDING"
    assert older.sent_to_ea_at is None
    assert sent_audits[older_id] == 0
    assert db.query(models.Execution).count() == 0

    delivered = polled.json()["command"]
    if delivered is None:
        # Prove the narrower known failure, not a fixture/HTTP/audit failure.
        assert eligible.status == "PENDING"
        assert eligible.sent_to_ea_at is None
        assert sent_audits[eligible_id] == 0
        raise _RevokedOldestPendingStarvesActiveSibling(
            "Older feed A was revoked, but eligible sibling feed B remained "
            "PENDING and was not delivered to the same subscriber"
        )

    assert delivered["command_id"] == eligible_id
    assert eligible.status == "SENT_TO_EA"
    assert eligible.sent_to_ea_at is not None
    assert sent_audits[eligible_id] == 1

    # A second poll must not resend the eligible command or touch the revoked
    # older one (no execution, notification or duplicate SENT audit).
    db.rollback()  # Release fixture read transaction before the second poll.
    repeated = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": user["id"]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["command"] is None
    db.expire_all()
    assert db.get(models.Command, older_id).status == "PENDING"
    assert db.get(models.Command, eligible_id).status == "SENT_TO_EA"
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == older_id,
        )
        .count()
        == 0
    )
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == eligible_id,
        )
        .count()
        == 1
    )
    assert db.query(models.Execution).count() == 0

def test_same_subscriber_tied_timestamp_revoked_heads_skip_to_active_feed(client, db):
    """Two revoked commands sharing a timestamp cannot hide a valid sibling.

    The deterministic (created_at, id) cursor must advance over both
    ineligible heads, including the timestamp tie, without producing SENT
    receipts for them. Fabricated HTTP/ORM fixtures only: no broker/EA trade.
    """
    provider, first_feed, raw_key = _provider(db, "same-time-revoked-heads")
    feeds = [
        first_feed,
        crud.create_feed(db, provider, "Second revoked", "tie-revoked-two"),
        crud.create_feed(db, provider, "Eligible sibling", "tie-active-three"),
    ]
    db.commit()  # Release fixture audit locks before HTTP registration.
    user = register_user(
        client, "990097", "synthetic_tied_head", "Synthetic Subscriber"
    )
    subscriptions = []
    account_ids = []
    for feed in feeds:
        subscription, account = crud.subscribe_user_to_feed(
            db, provider, feed, db.get(models.User, user["id"])
        )
        subscriptions.append(subscription)
        account_ids.append(account.id)
    db.commit()
    assert len(set(account_ids)) == 1

    command_subscriptions = []
    for feed, subscription in zip(feeds, subscriptions):
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
        assert approved.json()["result"] == "APPROVED"
        command_subscriptions.append((approved.json()["command_id"], subscription))
    assert len({command_id for command_id, _ in command_subscriptions}) == 3

    # Explicitly force a tie: order must be broken by command ID, rather than
    # relying on sub-millisecond wall-clock differences between approvals.
    tied_at = models.utcnow()
    for command_id, _ in command_subscriptions:
        command = db.get(models.Command, command_id)
        assert command.status == "PENDING"
        command.created_at = tied_at
    db.commit()
    db.expire_all()
    assert len({
        db.get(models.Command, command_id).created_at
        for command_id, _ in command_subscriptions
    }) == 1

    ordered = sorted(command_subscriptions, key=lambda pair: pair[0])
    revoked_ids = [command_id for command_id, _ in ordered[:2]]
    eligible_id = ordered[2][0]
    for _, subscription in ordered[:2]:
        subscription.status = "INACTIVE"
    db.commit()
    db.expire_all()
    for command_id, subscription in ordered:
        expected = "ACTIVE" if command_id == eligible_id else "INACTIVE"
        assert db.get(models.Subscription, subscription.id).status == expected
    db.rollback()  # Do not hold fixture read locks across the HTTP poll.

    polled = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": user["id"]},
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["command"] is not None
    assert polled.json()["command"]["command_id"] == eligible_id

    db.expire_all()
    for command_id in revoked_ids + [eligible_id]:
        command = db.get(models.Command, command_id)
        expected_status = "SENT_TO_EA" if command_id == eligible_id else "PENDING"
        expected_audits = 1 if command_id == eligible_id else 0
        assert command.status == expected_status
        assert (command.sent_to_ea_at is not None) == (command_id == eligible_id)
        assert (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
            == expected_audits
        )
    assert db.query(models.Execution).count() == 0

    db.rollback()
    repeated = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": user["id"]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["command"] is None
    db.expire_all()
    for command_id in revoked_ids + [eligible_id]:
        assert db.get(models.Command, command_id).status == (
            "SENT_TO_EA" if command_id == eligible_id else "PENDING"
        )
        assert (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
            == (1 if command_id == eligible_id else 0)
        )
    assert db.query(models.Execution).count() == 0

