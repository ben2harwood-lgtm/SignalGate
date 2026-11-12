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


@pytest.mark.parametrize("missing_field", ("provider_id", "feed_id", "account_id"))
def test_incomplete_provider_tenancy_never_claimed(client, db, missing_field):
    """A corrupt/legacy partial tenant link cannot reach the demo EA.

    All three nullable ownership columns are required together for a hosted
    provider command. Keep the deliberate all-null local-demo compatibility
    separate; no real provider, EA, broker, or trading data is used here.
    """
    provider, feed, raw_key = _provider(db, f"partial-tenant-{missing_field}")
    db.commit()
    user = register_user(
        client, "990099", f"synthetic_partial_{missing_field}", "Synthetic Subscriber"
    )
    crud.subscribe_user_to_feed(
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
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]
    command = db.get(models.Command, command_id)
    assert command is not None and command.status == "PENDING"
    assert all((command.provider_id, command.feed_id, command.account_id))

    # Deliberately corrupt one nullable tenant link *after* approval. It must
    # not be treated as an old all-null local-demo command on the next poll.
    setattr(command, missing_field, None)
    db.commit()
    db.expire_all()
    persisted = db.get(models.Command, command_id)
    assert getattr(persisted, missing_field) is None
    assert sum(value is None for value in (
        persisted.provider_id, persisted.feed_id, persisted.account_id
    )) == 1
    db.rollback()  # Release fixture read locks before the separate poll.

    polled = client.get(
        "/commands/pending", headers=EA_HEADERS, params={"user_id": user["id"]}
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["command"] is None

    db.expire_all()
    command = db.get(models.Command, command_id)
    assert command.status == "PENDING"
    assert command.sent_to_ea_at is None
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count()
        == 0
    )
    assert db.query(models.Execution).count() == 0


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



@pytest.mark.parametrize(
    "cursor_case",
    ("staggered", "same_time_revoked_first", "same_time_eligible_first"),
    ids=("staggered", "same-time-revoked-first", "same-time-eligible-first"),
)
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
def test_same_subscriber_cross_provider_revocation_skips_ineligible_oldest(
    client, db, revoked_scope, cursor_case
):
    """An earlier revoked tenant cannot block this user's other provider.

    Separate providers/organisations and trading accounts share *one* user.
    Both commands were explicitly YES-approved while valid. This catches a
    global early return or a broken cross-provider keyset poll; it does not
    grant execution, broker, pilot or independent acceptance.
    """
    import datetime as dt

    provider_a, feed_a, key_a = _provider(db, f"cross-provider-a-{revoked_scope}")
    provider_b, feed_b, key_b = _provider(db, f"cross-provider-b-{revoked_scope}")
    assert provider_a.organization_id != provider_b.organization_id
    db.commit()
    user = register_user(
        client,
        "990099" if revoked_scope == "provider_paused" else "990100",
        f"synthetic_cross_provider_{revoked_scope}",
        "Synthetic Subscriber",
    )
    subscription_a, account_a = crud.subscribe_user_to_feed(
        db, provider_a, feed_a, db.get(models.User, user["id"])
    )
    subscription_b, account_b = crud.subscribe_user_to_feed(
        db, provider_b, feed_b, db.get(models.User, user["id"])
    )
    db.commit()
    assert subscription_a.provider_id != subscription_b.provider_id
    assert account_a.id != account_b.id
    assert account_a.provider_id == provider_a.id
    assert account_b.provider_id == provider_b.id

    approved_ids = []
    for provider, feed, key in (
        (provider_a, feed_a, key_a),
        (provider_b, feed_b, key_b),
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
        approved_ids.append(approved.json()["command_id"])

    # Command IDs are random. Exercise both tie orders: a revoked command
    # before the eligible sibling (cursor must skip), and an eligible sibling
    # before the revoked one (subsequent polls must not leak the latter).
    tie_created_at = cursor_case != "staggered"
    swap_tied_order = tie_created_at and (
        (cursor_case == "same_time_revoked_first" and approved_ids[0] > approved_ids[1])
        or (cursor_case == "same_time_eligible_first" and approved_ids[0] < approved_ids[1])
    )
    if swap_tied_order:
        approved_ids.reverse()
        provider_a, provider_b = provider_b, provider_a
        feed_a, feed_b = feed_b, feed_a
        subscription_a, subscription_b = subscription_b, subscription_a
        account_a, account_b = account_b, account_a

    revoked_id, eligible_id = approved_ids
    assert revoked_id != eligible_id
    revoked = db.get(models.Command, revoked_id)
    eligible = db.get(models.Command, eligible_id)
    assert revoked.status == eligible.status == "PENDING"
    assert revoked.user_id == eligible.user_id == user["id"]
    assert revoked.account_id == account_a.id
    assert eligible.account_id == account_b.id
    # Exercise time-separated candidates and timestamp ties across
    # distinct providers. On a tie the (created_at, id) cursor must still
    # skip revoked A without hiding the eligible B command for this EA user.
    ordered_at = models.utcnow()
    revoked.created_at = ordered_at
    eligible.created_at = (
        ordered_at if tie_created_at else ordered_at + dt.timedelta(seconds=1)
    )
    if cursor_case == "same_time_revoked_first":
        assert revoked_id < eligible_id, "Tied revoked A must sort before eligible B"
    elif cursor_case == "same_time_eligible_first":
        assert eligible_id < revoked_id, "Tied eligible B must sort before revoked A"
    if revoked_scope == "provider_paused":
        provider_a.paused = True
        revoked_model, revoked_entity_id, field, expected = models.Provider, provider_a.id, "paused", True
    elif revoked_scope == "feed_paused":
        feed_a.paused = True
        revoked_model, revoked_entity_id, field, expected = models.Feed, feed_a.id, "paused", True
    elif revoked_scope == "provider_inactive":
        provider_a.status = "INACTIVE"
        revoked_model, revoked_entity_id, field, expected = models.Provider, provider_a.id, "status", "INACTIVE"
    elif revoked_scope == "feed_inactive":
        feed_a.status = "INACTIVE"
        revoked_model, revoked_entity_id, field, expected = models.Feed, feed_a.id, "status", "INACTIVE"
    elif revoked_scope == "subscription_inactive":
        subscription_a.status = "INACTIVE"
        revoked_model, revoked_entity_id, field, expected = models.Subscription, subscription_a.id, "status", "INACTIVE"
    elif revoked_scope == "account_inactive":
        account_a.status = "INACTIVE"
        revoked_model, revoked_entity_id, field, expected = models.TradingAccount, account_a.id, "status", "INACTIVE"
    else:
        raise AssertionError(f"Unknown revocation scope: {revoked_scope}")

    db.commit()
    # Verify the time order survived persistence, not just dirty ORM state.
    db.expire_all()
    assert db.get(models.Command, revoked_id).created_at == ordered_at
    assert db.get(models.Command, eligible_id).created_at == (
        ordered_at if tie_created_at else ordered_at + dt.timedelta(seconds=1)
    )
    # Prove the actual database persisted A's revocation and B's continuing
    # authority, instead of relying on dirty in-memory ORM objects.
    db.expire_all()
    assert getattr(db.get(revoked_model, revoked_entity_id), field) == expected
    assert db.get(models.Provider, provider_b.id).status == "ACTIVE"
    assert db.get(models.Provider, provider_b.id).paused is False
    assert db.get(models.Feed, feed_b.id).status == "ACTIVE"
    assert db.get(models.Feed, feed_b.id).paused is False
    assert db.get(models.Subscription, subscription_b.id).status == "ACTIVE"
    assert db.get(models.TradingAccount, account_b.id).status == "ACTIVE"
    assert db.get(models.Command, revoked_id).status == "PENDING"
    assert db.get(models.Command, eligible_id).status == "PENDING"
    db.rollback()  # Release fixture locks before the independent EA poll.

    polled = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": user["id"]},
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["command"] is not None
    assert polled.json()["command"]["command_id"] == eligible_id

    db.expire_all()
    assert db.get(models.Command, revoked_id).status == "PENDING"
    assert db.get(models.Command, revoked_id).sent_to_ea_at is None
    assert db.get(models.Command, eligible_id).status == "SENT_TO_EA"
    for command_id, expected_count in ((revoked_id, 0), (eligible_id, 1)):
        assert (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
            == expected_count
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
    assert db.get(models.Command, revoked_id).status == "PENDING"
    assert db.get(models.Command, eligible_id).status == "SENT_TO_EA"
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id.in_((revoked_id, eligible_id)),
        )
        .count()
        == 1
    )
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



@pytest.mark.parametrize("revoked_count", (20, 100))
def test_revoked_head_backlog_keeps_eligible_sibling_reachable(
    client, db, revoked_count, record_property
):
    """Synthetic 20/100-head backlog: delivery safety and query counts.

    The query count is an *upper sanity bound*, not a release latency SLO.
    This exercises the real EA-poll route on both SQLite and PostgreSQL.
    It does not prove production-scale performance or broker acceptance.
    """
    from sqlalchemy import event

    from app.database import engine

    provider, revoked_feed, raw_key = _provider(db, "synthetic-backlog-provider")
    active_feed = crud.create_feed(
        db, provider, "Active sibling", "synthetic-backlog-active-source"
    )
    db.commit()
    user = register_user(
        client, "990098", "synthetic_backlog_user", "Synthetic Subscriber"
    )
    revoked_membership, first_account = crud.subscribe_user_to_feed(
        db, provider, revoked_feed, db.get(models.User, user["id"])
    )
    active_membership, second_account = crud.subscribe_user_to_feed(
        db, provider, active_feed, db.get(models.User, user["id"])
    )
    db.commit()
    assert first_account.id == second_account.id
    assert revoked_membership.id != active_membership.id

    revoked_ids = []
    for _ in range(revoked_count):
        created = client.post(
            "/signals/create",
            headers=_headers(provider, raw_key),
            json={"feed_id": revoked_feed.id, "raw_text": VALID},
        )
        assert created.status_code == 200, created.text
        assert created.json()["parser_status"] == "VALID"
        approved = client.post(
            f"/signals/{created.json()['id']}/approve",
            json={"telegram_user_id": user["telegram_user_id"]},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["result"] == "APPROVED"
        revoked_ids.append(approved.json()["command_id"])

    created = client.post(
        "/signals/create",
        headers=_headers(provider, raw_key),
        json={"feed_id": active_feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    eligible_id = approved.json()["command_id"]
    assert len(set(revoked_ids + [eligible_id])) == revoked_count + 1

    # Explicitly keep the eligible command last, independent of clock speed.
    ordered_at = models.utcnow()
    for command_id in revoked_ids:
        db.get(models.Command, command_id).created_at = ordered_at
    eligible = db.get(models.Command, eligible_id)
    eligible.created_at = ordered_at + __import__("datetime").timedelta(seconds=1)
    revoked_membership.status = "INACTIVE"
    db.commit()
    db.rollback()  # Do not hold fixture locks across the API's claim transaction.

    claim_selects = []
    all_sql_statements = []
    def observe(_conn, _cursor, statement, _params, _context, _many):
        # The command-only count misses tenant/pause reads performed per
        # skipped revoked head. Count every request SQL round trip as well.
        all_sql_statements.append(statement)
        sql = statement.lower()
        if sql.lstrip().startswith("select") and "from commands" in sql:
            claim_selects.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        response = client.get(
            "/commands/pending",
            headers=EA_HEADERS,
            params={"user_id": user["id"]},
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    assert response.json()["command"] is not None
    assert response.json()["command"]["command_id"] == eligible_id
    # This is deliberately not a latency threshold; a future batch-select
    # optimisation should be allowed to use *fewer* round trips.
    assert 1 <= len(claim_selects) <= len(revoked_ids) + 1
    # Loose statement-count guard, NOT a latency or production SLO. The
    # claim currently reads the provider/feed/subscription for every skipped
    # head; command SELECT counts alone substantially understate DB work.
    assert len(claim_selects) <= len(all_sql_statements) <= 10 * (revoked_count + 1) + 30
    record_property("revoked_backlog_size", revoked_count)
    record_property("first_poll_command_selects", len(claim_selects))
    record_property("first_poll_all_sql_statements", len(all_sql_statements))

    db.expire_all()
    assert db.get(models.Command, eligible_id).status == "SENT_TO_EA"
    assert all(
        db.get(models.Command, command_id).status == "PENDING"
        for command_id in revoked_ids
    )
    sent = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id.in_(revoked_ids + [eligible_id]),
        )
        .all()
    )
    assert len(sent) == 1 and sent[0].entity_id == eligible_id
    assert db.query(models.Execution).count() == 0

    db.rollback()
    # Measure the second poll too: these revoked rows are deliberately left
    # PENDING and may be scanned again. Observation is not a latency SLO.
    claim_selects.clear()
    all_sql_statements.clear()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        repeated = client.get(
            "/commands/pending",
            headers=EA_HEADERS,
            params={"user_id": user["id"]},
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["command"] is None
    assert 1 <= len(claim_selects) <= revoked_count + 1
    assert len(claim_selects) <= len(all_sql_statements) <= 10 * (revoked_count + 1) + 30
    record_property("repeat_poll_command_selects", len(claim_selects))
    record_property("repeat_poll_all_sql_statements", len(all_sql_statements))
    db.expire_all()
    assert db.get(models.Command, eligible_id).status == "SENT_TO_EA"
    assert all(
        db.get(models.Command, command_id).status == "PENDING"
        for command_id in revoked_ids
    )
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id.in_(revoked_ids + [eligible_id]),
        )
        .count()
        == 1
    )
    assert db.query(models.Execution).count() == 0
