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




class _HostedTenantlessCommandDelivered(AssertionError):
    """An original local-demo command reached a licence-authenticated hosted EA."""


def test_hosted_licence_refuses_originally_tenantless_demo_command(
    client, db, monkeypatch
):
    """Historic all-null local authority must not migrate into hosted delivery.

    A *genuine* historical local-demo signal, YES and pending command are
    created while local mode is active. Switch only the synthetic request's
    licence gate to hosted and supply this same user's otherwise valid EA
    licence. No broker, EA process, Telegram, external data or schema is used.
    This is a migration/policy witness, not a deployed exploit.
    """
    from .conftest import create_signal

    user = register_user(
        client, "990300", "synthetic_hosted_legacy", "Synthetic Subscriber"
    )
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]
    command = db.get(models.Command, command_id)
    origin = db.get(models.Signal, command.signal_id)
    approval = db.get(models.Approval, command.approval_id)
    assert (command.provider_id, command.feed_id, command.account_id) == (
        None, None, None
    )
    assert (origin.provider_id, origin.feed_id) == (None, None)
    assert (approval.user_id, approval.signal_id, approval.decision, approval.status) == (
        user["id"], command.signal_id, "YES", "APPROVED"
    )
    assert command.status == "PENDING"
    db.rollback()

    # Preserve old local-mode positive tests. This explicitly tests a
    # licence-authenticated claim against a legacy row, not hosted startup.
    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        result = client.get(
            "/commands/pending",
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": user["license_key"],
            },
        )
    assert result.status_code == 200, result.text

    db.expire_all()
    command = db.get(models.Command, command_id)
    sent = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count()
    )
    assert db.query(models.Execution).count() == 0
    if result.json()["command"] is not None:
        # Exact unexpected delivery must fail this mandatory safety regression.
        assert result.json()["command"]["command_id"] == command_id
        assert command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None and sent == 1
        raise _HostedTenantlessCommandDelivered(
            "Hosted licence claimed historically tenantless local-demo command"
        )
    assert result.json()["command"] is None
    assert command.status == "PENDING"
    assert command.sent_to_ea_at is None and sent == 0


@pytest.mark.parametrize("origin_missing", (None, "provider_id", "feed_id"))
def test_hosted_provider_command_with_all_tenant_links_lost_never_delivered(
    client, db, origin_missing
):
    """A valid licence cannot reinstate a provider command with lost links.

    This simulates loss of all three Command ownership fields after a real
    synthetic provider YES. The original Signal's complete or partially
    missing provider/feed origin must prevent the historical local fallback.
    This tests a hosted-mode claim path, not real hosted startup,
    exploitation proof, EA execution, or broker acceptance.
    """
    provider, feed, raw_key = _provider(db, "hosted-all-null-command")
    db.commit()
    user = register_user(
        client, "990098", "synthetic_hosted_lost_tenancy", "Synthetic Subscriber"
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
    assert command.status == "PENDING"
    assert all((command.provider_id, command.feed_id, command.account_id))

    origin = db.get(models.Signal, command.signal_id)
    assert origin is not None
    assert (origin.provider_id, origin.feed_id) == (provider.id, feed.id)
    command.provider_id = None
    command.feed_id = None
    command.account_id = None
    if origin_missing is not None:
        setattr(origin, origin_missing, None)
    db.commit()
    db.expire_all()
    persisted_origin = db.get(models.Signal, origin.id)
    assert (
        persisted_origin.provider_id,
        persisted_origin.feed_id,
    ) == (
        None if origin_missing == "provider_id" else provider.id,
        None if origin_missing == "feed_id" else feed.id,
    )
    persisted = db.get(models.Command, command_id)
    assert (
        persisted.provider_id,
        persisted.feed_id,
        persisted.account_id,
    ) == (None, None, None)
    db.rollback()

    previous = crud.settings.require_license
    crud.settings.require_license = True
    try:
        polled = client.get(
            "/commands/pending",
            headers={**EA_HEADERS, "X-SG-License-Key": user["license_key"]},
        )
    finally:
        crud.settings.require_license = previous
    assert polled.status_code == 200, polled.text

    db.expire_all()
    command = db.get(models.Command, command_id)
    sent_audits = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count()
    )
    assert db.query(models.Execution).count() == 0
    # Even with a valid hosted licence, a fully or partially provider-scoped
    # origin is never a historical local-demo signal. No SENT audit may occur.
    assert polled.json()["command"] is None
    assert command.status == "PENDING"
    assert command.sent_to_ea_at is None
    assert sent_audits == 0



def test_fully_scoped_command_with_other_provider_origin_never_delivered(client, db):
    """A valid B membership cannot launder an A-approved signal into B.

    Synthetic integrity-fault regression only: this deliberately rebinds the
    fully scoped Command ownership columns in the database after an actual
    synthetic YES. It does not demonstrate an external corruption primitive
    or broker execution. A clean fix must preserve historical local demo.
    """
    provider_a, feed_a, raw_key_a = _provider(db, "origin-mismatch-a")
    provider_b, feed_b, _ = _provider(db, "origin-mismatch-b")
    assert provider_a.organization_id != provider_b.organization_id
    db.commit()
    user = register_user(
        client, "990097", "synthetic_origin_mismatch", "Synthetic Subscriber"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider_a, feed_a, db.get(models.User, user["id"])
    )
    subscription_b, account_b = crud.subscribe_user_to_feed(
        db, provider_b, feed_b, db.get(models.User, user["id"])
    )
    assert account_a.id != account_b.id
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider_a, raw_key_a),
        json={"feed_id": feed_a.id, "raw_text": VALID},
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
    assert (command.provider_id, command.feed_id, command.account_id) == (
        provider_a.id, feed_a.id, account_a.id
    )
    origin_id = command.signal_id
    origin = db.get(models.Signal, origin_id)
    assert (origin.provider_id, origin.feed_id) == (provider_a.id, feed_a.id)

    # Corrupt all three Command links to a separate, otherwise valid tenant.
    # A naive "check the new links" gate now passes, despite Signal A origin.
    command.provider_id = provider_b.id
    command.feed_id = feed_b.id
    command.account_id = account_b.id
    db.commit()
    db.expire_all()
    command = db.get(models.Command, command_id)
    assert (command.provider_id, command.feed_id, command.account_id) == (
        provider_b.id, feed_b.id, account_b.id
    )
    origin = db.get(models.Signal, origin_id)
    assert (origin.provider_id, origin.feed_id) == (provider_a.id, feed_a.id)
    assert db.get(models.Provider, provider_b.id).status == "ACTIVE"
    assert db.get(models.Subscription, subscription_b.id).status == "ACTIVE"
    db.rollback()  # Release test-session read locks before independent poll.

    polled = client.get(
        "/commands/pending", headers=EA_HEADERS, params={"user_id": user["id"]}
    )
    assert polled.status_code == 200, polled.text

    db.expire_all()
    command = db.get(models.Command, command_id)
    sent_audits = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count()
    )
    assert db.query(models.Execution).count() == 0
    # The independently stored A-origin must override B's otherwise active
    # provider/feed/subscription/account rows, with no SENT audit or execution.
    assert polled.json()["command"] is None
    assert command.status == "PENDING"
    assert command.sent_to_ea_at is None
    assert sent_audits == 0


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


def test_postgresql_original_signal_feed_writer_serializes_with_pending_claim(
    client, db
):
    """A held origin-feed rewrite must not be outrun by a pending EA claim.

    Offline two-session PostgreSQL witness for the original Signal FOR SHARE
    check: the writer flushes a fabricated *same-provider sibling feed*
    reassignment first; the pending claim must wait, re-read the committed
    origin, and refuse the now-mismatched Command. Restoring the authentic
    original feed is a normal positive control. No EA, broker, execution,
    real provider, customer data, or external service is involved.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL writer and claim sessions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    from sqlalchemy import event, text as sql_text

    from app.database import SessionLocal

    provider, original_feed, raw_key = _provider(db, "pg-origin-writer-first")
    sibling_feed = crud.create_feed(
        db, provider, "Synthetic sibling feed", "pg-origin-sibling-source"
    )
    db.commit()  # Release audit-chain lock before the separate HTTP requests.
    user = register_user(
        client, "990096", "synthetic_origin_writer", "Synthetic Subscriber"
    )
    crud.subscribe_user_to_feed(
        db, provider, original_feed, db.get(models.User, user["id"])
    )
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider, raw_key),
        json={"feed_id": original_feed.id, "raw_text": VALID},
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
    signal_id = created.json()["id"]
    original_feed_id, sibling_feed_id, user_id, provider_id = (
        original_feed.id, sibling_feed.id, user["id"], provider.id
    )
    assert original_feed_id != sibling_feed_id
    assert db.get(models.Command, command_id).status == "PENDING"
    assert db.get(models.Signal, signal_id).feed_id == original_feed_id
    db.rollback()  # Do not hold fixture locks across the actual race.

    writer_flushed = Event()
    release_writer = Event()
    claim_origin_select_attempted = Event()
    writer_pids = []
    claim_pids = []

    def rewrite_origin_and_hold():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            writer_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            origin = session.get(models.Signal, signal_id)
            assert origin is not None
            assert (origin.provider_id, origin.feed_id) == (
                provider_id, original_feed_id
            )
            origin.feed_id = sibling_feed_id
            session.flush()  # Real UPDATE holds the origin row until commit.
            writer_flushed.set()
            assert release_writer.wait(timeout=15), "Origin writer not released"
            session.commit()

    def claim_while_origin_is_uncommitted():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            claim_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

            def observe_origin_select(_conn, _cursor, statement, _params, _ctx, _many):
                lowered = statement.lower()
                if lowered.lstrip().startswith("select") and "from signals" in lowered:
                    claim_origin_select_attempted.set()

            event.listen(conn, "before_cursor_execute", observe_origin_select)
            claimed = crud.get_pending_command_for_user(session, user_id)
            claimed_id = claimed.id if claimed is not None else None
            session.commit()
            return claimed_id

    with ThreadPoolExecutor(max_workers=2) as workers:
        writer_future = workers.submit(rewrite_origin_and_hold)
        try:
            assert writer_flushed.wait(timeout=8), "Origin UPDATE not flushed"
            claim_future = workers.submit(claim_while_origin_is_uncommitted)
            assert claim_origin_select_attempted.wait(timeout=8), (
                "Claim did not reach original Signal lookup"
            )
            # Prove a *real* Signal row-lock wait instead of passing because
            # the worker was late, sleeping, or deadlocked elsewhere.
            observed_origin_blocker = False
            deadline = monotonic() + 2.5
            while monotonic() < deadline:
                with SessionLocal() as observer:
                    observer.execute(sql_text("SELECT pg_stat_clear_snapshot()"))
                    blockers = observer.scalar(
                        sql_text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": claim_pids[0]},
                    )
                if writer_pids[0] in blockers:
                    observed_origin_blocker = True
                    break
                if claim_future.done():
                    break
                sleep(0.05)
            assert observed_origin_blocker, (
                "Claim did not wait on the writer's original-Signal row lock"
            )
            assert not claim_future.done(), "Claim escaped held origin mutation"
        finally:
            release_writer.set()
        writer_future.result(timeout=20)
        claimed_id = claim_future.result(timeout=20)

    assert len(writer_pids) == len(claim_pids) == 1
    assert writer_pids[0] != claim_pids[0], "Not two PostgreSQL sessions"
    assert claimed_id is None, "A mismatched original feed reached the demo EA"
    with SessionLocal() as verify:
        origin = verify.get(models.Signal, signal_id)
        command = verify.get(models.Command, command_id)
        assert (origin.provider_id, origin.feed_id) == (
            provider_id, sibling_feed_id
        )
        assert (command.provider_id, command.feed_id) == (
            provider_id, original_feed_id
        )
        assert command.status == "PENDING"
        assert command.sent_to_ea_at is None
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 0
        )
        assert verify.query(models.Execution).count() == 0

    # Positive control: after an independently committed restoration to the
    # authentic provider/feed, an approved eligible command is still claimable.
    with SessionLocal() as restore:
        origin = restore.get(models.Signal, signal_id)
        origin.feed_id = original_feed_id
        restore.commit()
    with SessionLocal() as claim_restored:
        claimed = crud.get_pending_command_for_user(claim_restored, user_id)
        assert claimed is not None and claimed.id == command_id
        claim_restored.commit()
    with SessionLocal() as verify:
        command = verify.get(models.Command, command_id)
        assert command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 1
        )
        assert verify.query(models.Execution).count() == 0


def test_postgresql_pending_claim_blocks_later_signal_origin_rewrite(client, db):
    """Claim-first commit ordering: origin mutation waits for the EA claim.

    Two real offline PostgreSQL sessions, synthetic provider approval only.
    This complements the writer-first regression above. It demonstrates
    mutual serialization of the original Signal row at the claim boundary,
    not broker execution, independent assurance, or real-world acceptance.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL claim and writer sessions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    from sqlalchemy import text as sql_text

    from app.database import SessionLocal

    provider, original_feed, raw_key = _provider(db, "pg-claim-origin-first")
    sibling = crud.create_feed(
        db, provider, "Synthetic other feed", "pg-claim-origin-sibling"
    )
    db.commit()
    user = register_user(
        client, "990097", "synthetic_claim_first", "Synthetic Subscriber"
    )
    crud.subscribe_user_to_feed(
        db, provider, original_feed, db.get(models.User, user["id"])
    )
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider, raw_key),
        json={"feed_id": original_feed.id, "raw_text": VALID},
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
    signal_id = created.json()["id"]
    provider_id, original_feed_id, sibling_id, user_id = (
        provider.id, original_feed.id, sibling.id, user["id"]
    )
    assert original_feed_id != sibling_id
    assert db.get(models.Command, command_id).status == "PENDING"
    db.rollback()  # No fixture session lock may mask the independent race.

    claim_held = Event()
    allow_claim_commit = Event()
    writer_update_attempted = Event()
    claim_pids = []
    writer_pids = []

    def claim_and_hold_before_commit():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            claim_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            claimed = crud.get_pending_command_for_user(session, user_id)
            assert claimed is not None and claimed.id == command_id
            assert claimed.status == "SENT_TO_EA"
            claim_held.set()
            assert allow_claim_commit.wait(timeout=15), "Claim not released"
            session.commit()

    def rewrite_origin_after_claim():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            writer_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            signal = session.get(models.Signal, signal_id)
            assert signal is not None
            assert (signal.provider_id, signal.feed_id) == (
                provider_id, original_feed_id
            )
            signal.feed_id = sibling_id
            writer_update_attempted.set()
            session.flush()  # Must wait on claim's Signal FOR SHARE.
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as workers:
        claim_future = workers.submit(claim_and_hold_before_commit)
        try:
            assert claim_held.wait(timeout=8), "Claim did not reach lock point"
            writer_future = workers.submit(rewrite_origin_after_claim)
            assert writer_update_attempted.wait(timeout=8), (
                "Origin UPDATE was not attempted"
            )
            # pg_blocking_pids proves a genuine PostgreSQL lock wait, not
            # thread scheduling, sleep timing, or an unrelated mock.
            blocked_by_claim = False
            deadline = monotonic() + 2.5
            while monotonic() < deadline:
                with SessionLocal() as observer:
                    observer.execute(sql_text("SELECT pg_stat_clear_snapshot()"))
                    blockers = observer.scalar(
                        sql_text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": writer_pids[0]},
                    )
                if claim_pids[0] in blockers:
                    blocked_by_claim = True
                    break
                if writer_future.done():
                    break
                sleep(0.05)
            assert blocked_by_claim, (
                "Signal-origin writer did not wait for the pending claim"
            )
            assert not writer_future.done(), "Writer escaped an uncommitted claim"
        finally:
            allow_claim_commit.set()
        claim_future.result(timeout=20)
        writer_future.result(timeout=20)

    assert len(claim_pids) == len(writer_pids) == 1
    assert claim_pids[0] != writer_pids[0], "Not two PostgreSQL sessions"
    with SessionLocal() as verify:
        signal = verify.get(models.Signal, signal_id)
        command = verify.get(models.Command, command_id)
        assert (signal.provider_id, signal.feed_id) == (provider_id, sibling_id)
        assert (command.provider_id, command.feed_id) == (
            provider_id, original_feed_id
        )
        assert command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 1
        )
        assert verify.query(models.Execution).count() == 0

    # After the separately committed origin mutation, no second EA claim
    # or extra delivery audit may be produced for this already-SENT command.
    with SessionLocal() as repeat:
        assert crud.get_pending_command_for_user(repeat, user_id) is None
        repeat.commit()
    with SessionLocal() as verify:
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 1
        )
        assert verify.query(models.Execution).count() == 0


def test_approved_command_cannot_be_relabelled_to_other_subscriber(client, db):
    """A valid B licence/subscription must not inherit subscriber A's approval.

    Fabricated same-feed users; corruption of two Command ownership fields
    after A's genuine synthetic YES. This does not show an external mutation
    primitive or constitute MT5, broker, or independent acceptance evidence.
    Must pass on both SQLite and PostgreSQL. Neither an unexpected delivery
    nor a broken fixture may be hidden as an expected failure.
    """
    provider, feed, raw_key = _provider(db, "approval-owner-relabel")
    db.commit()
    subscriber_a = register_user(
        client, "990211", "synthetic_approval_owner_a", "Synthetic A"
    )
    subscriber_b = register_user(
        client, "990212", "synthetic_approval_owner_b", "Synthetic B"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber_a["id"])
    )
    subscription_b, account_b = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber_b["id"])
    )
    assert account_a.id != account_b.id
    assert subscription_b.status == "ACTIVE"
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
        json={"telegram_user_id": subscriber_a["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]
    command = db.get(models.Command, command_id)
    approval = db.get(models.Approval, command.approval_id)
    assert approval.user_id == subscriber_a["id"]
    assert approval.signal_id == command.signal_id
    assert approval.decision == "YES"
    assert command.user_id == subscriber_a["id"]
    assert (command.provider_id, command.feed_id, command.account_id) == (
        provider.id, feed.id, account_a.id
    )

    # Leave independently persisted Signal + Approval unchanged; give Command
    # B's otherwise valid subscriber/account links for this same provider/feed.
    command.user_id = subscriber_b["id"]
    command.account_id = account_b.id
    db.commit()
    db.expire_all()
    altered = db.get(models.Command, command_id)
    assert (altered.user_id, altered.account_id) == (
        subscriber_b["id"], account_b.id
    )
    original_approval = db.get(models.Approval, altered.approval_id)
    assert original_approval.user_id == subscriber_a["id"]
    db.rollback()  # Separate HTTP poll must not inherit test-session locks.

    previous_require_license = crud.settings.require_license
    crud.settings.require_license = True
    try:
        polled = client.get(
            "/commands/pending",
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": subscriber_b["license_key"],
            },
        )
    finally:
        crud.settings.require_license = previous_require_license
    assert polled.status_code == 200, polled.text

    db.expire_all()
    altered = db.get(models.Command, command_id)
    sent_count = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count()
    )
    assert db.query(models.Execution).count() == 0
    assert polled.json()["command"] is None
    assert altered.status == "PENDING"
    assert altered.sent_to_ea_at is None
    assert sent_count == 0

    # Positive control: the actual approving subscriber can still claim the
    # same command after its two altered links are restored. Do not mistake
    # a global deny-all for a passing provenance check.
    db.rollback()
    restored = db.get(models.Command, command_id)
    restored.user_id = subscriber_a["id"]
    restored.account_id = account_a.id
    db.commit()
    db.rollback()
    previous_require_license = crud.settings.require_license
    crud.settings.require_license = True
    try:
        original_owner_poll = client.get(
            "/commands/pending",
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": subscriber_a["license_key"],
            },
        )
    finally:
        crud.settings.require_license = previous_require_license
    assert original_owner_poll.status_code == 200, original_owner_poll.text
    assert original_owner_poll.json()["command"]["command_id"] == command_id

    db.expire_all()
    approved_command = db.get(models.Command, command_id)
    assert approved_command.status == "SENT_TO_EA"
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count() == 1
    )
    assert db.query(models.Execution).count() == 0

def test_postgresql_pending_claim_waits_for_approval_owner_rewrite(client, db):
    """A held Approval writer must finish before an EA can claim its YES.

    This is a synthetic, offline PostgreSQL writer-first concurrency witness.
    It proves a real Approval-row lock wait and denial after a subscriber
    provenance rewrite, not broker execution or independent acceptance.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL approval writer/claim sessions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    from sqlalchemy import event, text as sql_text

    from app.database import SessionLocal

    provider, feed, raw_key = _provider(db, "pg-approval-writer-first")
    db.commit()
    subscriber_a = register_user(
        client, "990213", "synthetic_approval_race_a", "Synthetic A"
    )
    subscriber_b = register_user(
        client, "990214", "synthetic_approval_race_b", "Synthetic B"
    )
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber_a["id"])
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
        json={"telegram_user_id": subscriber_a["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]
    command = db.get(models.Command, command_id)
    approval_id = command.approval_id
    original_user_id, replacement_user_id = (
        subscriber_a["id"], subscriber_b["id"]
    )
    original_approval = db.get(models.Approval, approval_id)
    assert original_approval.signal_id == command.signal_id
    assert original_approval.user_id == original_user_id
    assert (original_approval.decision, original_approval.status) == (
        "YES", "APPROVED"
    )
    assert command.status == "PENDING"
    db.rollback()  # Fixture session must not hold the race's row locks.

    writer_flushed = Event()
    release_writer = Event()
    claim_approval_select_attempted = Event()
    writer_pids = []
    claim_pids = []

    def change_approval_owner_and_hold():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            writer_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            approval = session.get(models.Approval, approval_id)
            assert approval is not None
            assert approval.user_id == original_user_id
            approval.user_id = replacement_user_id
            session.flush()  # PostgreSQL UPDATE locks Approval until commit.
            writer_flushed.set()
            assert release_writer.wait(timeout=15), "Approval writer not released"
            session.commit()

    def claim_while_approval_is_uncommitted():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            claim_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

            def observe_approval_select(_conn, _cursor, statement, _params, _ctx, _many):
                lowered = statement.lower()
                if lowered.lstrip().startswith("select") and "from approvals" in lowered:
                    claim_approval_select_attempted.set()

            event.listen(conn, "before_cursor_execute", observe_approval_select)
            claimed = crud.get_pending_command_for_user(
                session, original_user_id
            )
            claimed_id = claimed.id if claimed is not None else None
            session.commit()
            return claimed_id

    with ThreadPoolExecutor(max_workers=2) as workers:
        writer_future = workers.submit(change_approval_owner_and_hold)
        try:
            assert writer_flushed.wait(timeout=8), "Approval UPDATE not flushed"
            claim_future = workers.submit(claim_while_approval_is_uncommitted)
            assert claim_approval_select_attempted.wait(timeout=8), (
                "EA claim never reached original Approval lookup"
            )
            blocked_by_writer = False
            deadline = monotonic() + 2.5
            while monotonic() < deadline:
                with SessionLocal() as observer:
                    observer.execute(sql_text("SELECT pg_stat_clear_snapshot()"))
                    blockers = observer.scalar(
                        sql_text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": claim_pids[0]},
                    )
                if writer_pids[0] in blockers:
                    blocked_by_writer = True
                    break
                if claim_future.done():
                    break
                sleep(0.05)
            assert blocked_by_writer, (
                "Claim did not wait on the original Approval row UPDATE"
            )
            assert not claim_future.done(), "Claim escaped uncommitted Approval"
        finally:
            release_writer.set()
        writer_future.result(timeout=20)
        claimed_id = claim_future.result(timeout=20)

    assert len(writer_pids) == len(claim_pids) == 1
    assert writer_pids[0] != claim_pids[0], "Not two PostgreSQL sessions"
    assert claimed_id is None, "An A command escaped B-owned approval"
    with SessionLocal() as verify:
        approval = verify.get(models.Approval, approval_id)
        command = verify.get(models.Command, command_id)
        assert approval.user_id == replacement_user_id
        assert command.user_id == original_user_id
        assert command.status == "PENDING"
        assert command.sent_to_ea_at is None
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 0
        )
        assert verify.query(models.Execution).count() == 0

    # A true positive control: restoring original consent permits exactly one
    # ordinary demo EA claim, never a second delivery.
    with SessionLocal() as restore:
        approval = restore.get(models.Approval, approval_id)
        approval.user_id = original_user_id
        restore.commit()
    with SessionLocal() as claim_restored:
        claimed = crud.get_pending_command_for_user(
            claim_restored, original_user_id
        )
        assert claimed is not None and claimed.id == command_id
        claim_restored.commit()
    with SessionLocal() as repeat:
        assert crud.get_pending_command_for_user(
            repeat, original_user_id
        ) is None
        repeat.commit()
    with SessionLocal() as verify:
        command = verify.get(models.Command, command_id)
        assert command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 1
        )
        assert verify.query(models.Execution).count() == 0

def test_postgresql_pending_claim_blocks_later_approval_status_rewrite(client, db):
    """Claim-first Approval row lock blocks a later status change until commit.

    Synthetic offline PostgreSQL only: independent transactions, a genuine
    pg_blocking_pids lock wait, and an audit/Execution negative control. This
    does not exercise a real MT5 EA or establish independent acceptance.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL claim and approval writer sessions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    from sqlalchemy import text as sql_text

    from app.database import SessionLocal

    provider, feed, raw_key = _provider(db, "pg-approval-claim-first")
    db.commit()
    user = register_user(
        client, "990215", "synthetic_claim_first_approval", "Synthetic Subscriber"
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
    user_id = user["id"]
    command = db.get(models.Command, command_id)
    approval_id = command.approval_id
    original = db.get(models.Approval, approval_id)
    assert (original.user_id, original.signal_id) == (
        user_id, command.signal_id
    )
    assert (original.decision, original.status) == ("YES", "APPROVED")
    assert command.status == "PENDING"
    db.rollback()  # No fixture-session locks must masquerade as the claim lock.

    claim_held = Event()
    allow_claim_commit = Event()
    approval_update_attempted = Event()
    claim_pids = []
    writer_pids = []

    def claim_and_hold_before_commit():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            claim_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            claimed = crud.get_pending_command_for_user(session, user_id)
            assert claimed is not None and claimed.id == command_id
            assert claimed.status == "SENT_TO_EA"
            claim_held.set()
            assert allow_claim_commit.wait(timeout=15), "Claim was not released"
            session.commit()

    def rewrite_approval_after_claim():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            writer_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            approval = session.get(models.Approval, approval_id)
            assert approval is not None
            assert (approval.decision, approval.status) == ("YES", "APPROVED")
            approval.status = "REJECTED"
            approval_update_attempted.set()
            session.flush()  # UPDATE must wait for the claim's Approval SHARE lock.
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as workers:
        claim_future = workers.submit(claim_and_hold_before_commit)
        try:
            assert claim_held.wait(timeout=8), "Claim not held before commit"
            writer_future = workers.submit(rewrite_approval_after_claim)
            assert approval_update_attempted.wait(timeout=8), (
                "Approval UPDATE was never attempted"
            )
            blocked_by_claim = False
            deadline = monotonic() + 2.5
            while monotonic() < deadline:
                with SessionLocal() as observer:
                    observer.execute(sql_text("SELECT pg_stat_clear_snapshot()"))
                    blockers = observer.scalar(
                        sql_text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": writer_pids[0]},
                    )
                if claim_pids[0] in blockers:
                    blocked_by_claim = True
                    break
                if writer_future.done():
                    break
                sleep(0.05)
            assert blocked_by_claim, (
                "Approval writer did not wait on original YES row SHARE lock"
            )
            assert not writer_future.done(), (
                "Approval UPDATE escaped an uncommitted demo EA claim"
            )
        finally:
            allow_claim_commit.set()
        claim_future.result(timeout=20)
        writer_future.result(timeout=20)

    assert len(claim_pids) == len(writer_pids) == 1
    assert claim_pids[0] != writer_pids[0], "Not independent PostgreSQL sessions"
    with SessionLocal() as verify:
        command = verify.get(models.Command, command_id)
        approval = verify.get(models.Approval, approval_id)
        assert (approval.decision, approval.status) == ("YES", "REJECTED")
        assert command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 1
        )
        assert verify.query(models.Execution).count() == 0

    # The original command has already been sent exactly once. A later
    # Approval mutation must not create a duplicate SEND on another poll.
    with SessionLocal() as repeat:
        assert crud.get_pending_command_for_user(repeat, user_id) is None
        repeat.commit()
    with SessionLocal() as verify:
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count() == 1
        )
        assert verify.query(models.Execution).count() == 0


@pytest.mark.parametrize(
    "alteration",
    (
        "decision_no",
        "status_rejected",
        "signal_relabel",
        "approval_user_relabel",
        "command_approval_relabel",
    ),
)
def test_pending_claim_rechecks_original_yes_approval_fields(client, db, alteration):
    """A stale/corrupted or substituted YES cannot be delivered; restore works.

    Synthetic database-integrity faults only, not an external mutation
    primitive, broker execution, or independent security acceptance.
    """
    provider, feed, raw_key = _provider(db, f"approval-fields-{alteration}")
    db.commit()
    user = register_user(
        client, "990216", f"synthetic_approval_fields_{alteration}",
        "Synthetic Subscriber",
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
    approval_id = command.approval_id
    approval = db.get(models.Approval, approval_id)
    assert (approval.signal_id, approval.user_id) == (
        command.signal_id, user["id"]
    )
    assert (approval.decision, approval.status) == ("YES", "APPROVED")
    original_signal_id = approval.signal_id
    original_approval_user_id = approval.user_id
    if alteration == "decision_no":
        approval.decision = "NO"
    elif alteration == "status_rejected":
        approval.status = "REJECTED"
    elif alteration == "approval_user_relabel":
        # A different legitimate subscriber in the same feed cannot inherit
        # the original YES solely by changing the approval's owner.
        other_subscriber = register_user(
            client, "990217", "synthetic_approval_fields_other",
            "Synthetic Other Subscriber",
        )
        crud.subscribe_user_to_feed(
            db, provider, feed, db.get(models.User, other_subscriber["id"])
        )
        assert other_subscriber["id"] != original_approval_user_id
        approval.user_id = other_subscriber["id"]
    elif alteration == "signal_relabel":
        different_signal = client.post(
            "/signals/create",
            headers=_headers(provider, raw_key),
            json={"feed_id": feed.id, "raw_text": VALID},
        )
        assert different_signal.status_code == 200, different_signal.text
        assert different_signal.json()["id"] != original_signal_id
        approval.signal_id = different_signal.json()["id"]
    else:
        # The Command points at a different *valid YES* from the same subscriber
        # and provider, but that YES belongs to another signal. A valid
        # approval record cannot authorise the original command by substitution.
        different_signal = client.post(
            "/signals/create",
            headers=_headers(provider, raw_key),
            json={"feed_id": feed.id, "raw_text": VALID},
        )
        assert different_signal.status_code == 200, different_signal.text
        assert different_signal.json()["id"] != original_signal_id
        other_approval = crud._record_approval(
            db, db.get(models.Signal, different_signal.json()["id"]),
            db.get(models.User, user["id"]), "YES", "APPROVED",
        )
        assert other_approval.id != approval_id
        command.approval_id = other_approval.id
    db.commit()
    db.rollback()

    polled = client.get(
        "/commands/pending", headers=EA_HEADERS,
        params={"user_id": user["id"]},
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
        .count() == 0
    )
    assert db.query(models.Execution).count() == 0

    # Positive control: a restored original YES can be claimed once.
    db.rollback()
    approval = db.get(models.Approval, approval_id)
    approval.signal_id = original_signal_id
    approval.user_id = original_approval_user_id
    approval.decision = "YES"
    approval.status = "APPROVED"
    if alteration == "command_approval_relabel":
        db.get(models.Command, command_id).approval_id = approval_id
    db.commit()
    db.rollback()
    legitimate = client.get(
        "/commands/pending", headers=EA_HEADERS,
        params={"user_id": user["id"]},
    )
    assert legitimate.status_code == 200, legitimate.text
    assert legitimate.json()["command"]["command_id"] == command_id
    db.expire_all()
    assert db.get(models.Command, command_id).status == "SENT_TO_EA"
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count() == 1
    )
    assert db.query(models.Execution).count() == 0


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("received", {}),
        ("execution", {"status": "FAILED", "error_code": "SYNTHETIC"}),
        (
            "reconcile_open_position",
            {
                "broker_tickets": ["990343"],
                "executed_symbol": "XAUUSD",
                "executed_direction": "BUY",
                "executed_price": 2350.0,
                "lot_size": 0.1,
            },
        ),
        (
            "management_event",
            {"event_type": "FULLY_CLOSED", "stage": "FULLY_CLOSED", "result": "SUCCESS"},
        ),
    ],
)
def test_hosted_legacy_pending_callback_refused_before_any_ea_claim(
    client, db, monkeypatch, endpoint, payload
):
    """A valid hosted licence cannot forge an undelivered local-demo receipt.

    Four EA callback routes use the same hosted authorization boundary.
    The original command was approved locally but has never been SENT_TO_EA.
    Nothing here connects to an EA or broker or claims external acceptance.
    """
    from .conftest import create_signal
    from app.routes import commands as command_routes

    subscriber = register_user(
        client, "990343", "synthetic_legacy_pending_callback", "Synthetic Subscriber"
    )
    signal = create_signal(client, VALID)
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": subscriber["telegram_user_id"]},
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["result"] == "APPROVED"
    command_id = approval.json()["command_id"]
    command = db.get(models.Command, command_id)
    original_signal = db.get(models.Signal, command.signal_id)
    assert (command.provider_id, command.feed_id, command.account_id) == (
        None, None, None
    )
    assert (original_signal.provider_id, original_signal.feed_id) == (None, None)
    assert command.status == "PENDING" and command.sent_to_ea_at is None
    db.rollback()
    original_command_audits = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.entity_id == command_id)
        .count()
    )
    db.rollback()

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_k: None)
        reported = client.post(
            f"/commands/{command_id}/{endpoint}",
            json=payload,
            headers={**EA_HEADERS, "X-SG-License-Key": subscriber["license_key"]},
        )
    assert reported.status_code == 403, (endpoint, reported.text)
    db.expire_all()
    persisted = db.get(models.Command, command_id)
    assert persisted.status == "PENDING"
    assert persisted.sent_to_ea_at is None and persisted.processed_at is None
    assert (
        db.query(models.TradeManagementEvent)
        .filter(models.TradeManagementEvent.command_id == command_id)
        .count()
    ) == 0
    assert (
        db.query(models.Execution)
        .filter(models.Execution.command_id == command_id)
        .count()
    ) == 0
    assert (
        db.query(models.AuditLog)
        .filter(models.AuditLog.entity_id == command_id)
        .count()
    ) == original_command_audits


@pytest.mark.parametrize("account_status_after_delivery", ("ACTIVE", "INACTIVE"))
@pytest.mark.parametrize(
    "endpoint,payload,expected_status,expected_executions",
    [
        ("received", {}, "received", 0),
        (
            "execution",
            {"status": "FAILED", "error_code": "SYNTHETIC_REJECTION"},
            "ok",
            1,
        ),
        (
            "reconcile_open_position",
            {
                "broker_tickets": ["990344"],
                "executed_symbol": "EURUSD",
                "executed_direction": "BUY",
                "executed_price": 1.0850,
                "lot_size": 0.1,
            },
            "recovered",
            1,
        ),
    ],
)
def test_scoped_command_delivered_before_hosted_mode_keeps_ea_receipt_path(
    client, db, monkeypatch, endpoint, payload, expected_status,
    expected_executions, account_status_after_delivery
):
    """A previously delivered, tenant-scoped command retains broker-audit paths.

    This is a synthetic local-to-hosted mode-transition compatibility test.
    Unlike a historical tenantless command, the original Signal, approval,
    account and Command are provider/feed scoped. We preserve evidence from
    a command that was already SENT_TO_EA, even if its trading account is later
    deactivated; we do not connect to an EA/broker.
    """
    from app.routes import commands as command_routes

    provider, feed, key = _provider(db, "scoped-pre-hosted-ea-callback")
    db.commit()
    subscriber = register_user(
        client, "990344", "synthetic_scoped_ea_callback", "Synthetic Subscriber"
    )
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber["id"])
    )
    db.commit()
    created = client.post(
        "/signals/create",
        headers=_headers(provider, key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    approval = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": subscriber["telegram_user_id"]},
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["result"] == "APPROVED"
    command_id = approval.json()["command_id"]
    db.rollback()

    # Claim in local-demo mode, then simulate only the licence gate changing.
    claimed = client.get(
        "/commands/pending",
        params={"user_id": subscriber["id"]},
        headers=EA_HEADERS,
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["command"]["command_id"] == command_id
    db.expire_all()
    command = db.get(models.Command, command_id)
    original_signal = db.get(models.Signal, command.signal_id)
    assert (command.provider_id, command.feed_id) == (provider.id, feed.id)
    assert (original_signal.provider_id, original_signal.feed_id) == (
        provider.id, feed.id
    )
    assert command.status == "SENT_TO_EA" and command.sent_to_ea_at is not None
    original_account_id = command.account_id
    db.rollback()

    # A paused/inactive account must prevent *new* delivery, but cannot erase
    # the genuine historical audit path for a command already sent to the EA.
    # Offline mode transition and simulated account deactivation only.
    account = db.get(models.TradingAccount, original_account_id)
    assert account.user_id == subscriber["id"] and account.provider_id == provider.id
    if account_status_after_delivery == "INACTIVE":
        account.status = "INACTIVE"
        db.commit()
        db.rollback()
    assert db.get(models.TradingAccount, original_account_id).status == account_status_after_delivery
    db.rollback()

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_k: None)
        reported = client.post(
            f"/commands/{command_id}/{endpoint}",
            json=payload,
            headers={**EA_HEADERS, "X-SG-License-Key": subscriber["license_key"]},
        )
    assert reported.status_code == 200, (endpoint, reported.text)
    assert reported.json()["status"] == expected_status

    db.expire_all()
    command = db.get(models.Command, command_id)
    assert command.sent_to_ea_at is not None
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.entity_id == command_id,
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
        )
        .count()
    ) == 1
    assert (
        db.query(models.Execution)
        .filter(models.Execution.command_id == command_id)
        .count()
    ) == expected_executions


def test_hosted_delivered_command_relabel_cannot_transfer_execution_receipt(
    client, db, monkeypatch
):
    """Original subscriber approval must survive a post-delivery owner rewrite.

    Two legitimate licensed synthetic subscribers share a provider/feed.
    Subscriber A alone approves and claims a demo command. An intentional
    post-claim database-integrity fault rewrites the Command's user/account
    to B while leaving the original Signal and YES approval untouched.
    This is NOT proof of an external mutation path, broker fill or acceptance.
    A valid B licence is not a substitute for A's historical authorisation.
    """
    from app.routes import commands as command_routes

    provider, feed, key = _provider(db, "hosted-post-delivery-owner-drift")
    db.commit()
    subscriber_a = register_user(
        client, "990347", "synthetic_delivered_owner_a", "Synthetic A"
    )
    subscriber_b = register_user(
        client, "990348", "synthetic_delivered_owner_b", "Synthetic B"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber_a["id"])
    )
    _, account_b = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber_b["id"])
    )
    assert account_a.id != account_b.id
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider, key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": subscriber_a["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]
    db.rollback()

    claimed = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": subscriber_a["id"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["command"]["command_id"] == command_id
    db.expire_all()
    command = db.get(models.Command, command_id)
    approval = db.get(models.Approval, command.approval_id)
    assert command.status == "SENT_TO_EA" and command.sent_to_ea_at is not None
    assert command.user_id == approval.user_id == subscriber_a["id"]
    assert (command.provider_id, command.feed_id, command.account_id) == (
        provider.id, feed.id, account_a.id
    )
    original_approval_id = approval.id
    db.rollback()

    # Simulate corrupt mutable ownership after legitimate delivery. The
    # independent YES approval still binds only subscriber A.
    changed = db.get(models.Command, command_id)
    changed.user_id = subscriber_b["id"]
    changed.account_id = account_b.id
    db.commit()
    db.rollback()

    payload = {"status": "FAILED", "error_code": "SYNTHETIC_REJECT"}
    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_k: None)
        reported = client.post(
            f"/commands/{command_id}/execution",
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": subscriber_b["license_key"],
            },
            json=payload,
        )

    db.expire_all()
    command = db.get(models.Command, command_id)
    approval = db.get(models.Approval, original_approval_id)
    execution = (
        db.query(models.Execution)
        .filter(models.Execution.command_id == command_id)
        .one_or_none()
    )
    assert (approval.user_id, approval.signal_id, approval.decision) == (
        subscriber_a["id"], command.signal_id, "YES"
    )
    assert (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        )
        .count()
    ) == 1

    assert reported.status_code == 403, reported.text
    assert command.status == "SENT_TO_EA"
    assert execution is None

    # Positive control after a future fix: restoring historical owner fields
    # must still permit A's broker-audit receipt exactly once.
    db.rollback()
    restored = db.get(models.Command, command_id)
    restored.user_id = subscriber_a["id"]
    restored.account_id = account_a.id
    db.commit()
    db.rollback()
    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_k: None)
        original = client.post(
            f"/commands/{command_id}/execution",
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": subscriber_a["license_key"],
            },
            json=payload,
        )
    assert original.status_code == 200, original.text
    assert original.json()["status"] == "ok"
    db.expire_all()
    execution = db.query(models.Execution).filter(
        models.Execution.command_id == command_id
    ).one()
    assert execution.user_id == subscriber_a["id"]
    assert db.get(models.Command, command_id).status == "FAILED"


def test_hosted_delivered_command_account_only_relabel_cannot_forge_execution(
    client, db, monkeypatch
):
    """Historical owner approval must not authorize a foreign trading account.

    Subscriber A alone approves and receives a provider-scoped demo command.
    After delivery, a deliberate database-integrity fault changes ONLY the
    Command.account_id to B's legitimate account on the same feed, leaving its
    user, Signal, original YES and licence unchanged. A's licence must not
    attest an execution attributed to the foreign account. This is synthetic
    corruption, not an established external mutation primitive or broker fill.
    """
    from app.routes import commands as command_routes

    provider, feed, key = _provider(db, "hosted-delivered-account-only-drift")
    db.commit()
    subscriber_a = register_user(
        client, "990349", "synthetic_account_only_owner_a", "Synthetic A"
    )
    subscriber_b = register_user(
        client, "990350", "synthetic_account_only_owner_b", "Synthetic B"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber_a["id"])
    )
    _, account_b = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, subscriber_b["id"])
    )
    assert account_a.id != account_b.id
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider, key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": subscriber_a["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]
    db.rollback()

    claimed = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": subscriber_a["id"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["command"]["command_id"] == command_id
    db.expire_all()
    original = db.get(models.Command, command_id)
    yes = db.get(models.Approval, original.approval_id)
    assert original.status == "SENT_TO_EA" and original.sent_to_ea_at is not None
    assert original.user_id == yes.user_id == subscriber_a["id"]
    assert yes.signal_id == original.signal_id
    assert yes.decision == "YES"
    assert original.account_id == account_a.id
    db.rollback()

    changed = db.get(models.Command, command_id)
    changed.account_id = account_b.id  # ONLY the account link is corrupted.
    db.commit()
    db.rollback()

    payload = {"status": "FAILED", "error_code": "SYNTHETIC_ACCOUNT_REJECT"}
    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_k: None)
        reported = client.post(
            f"/commands/{command_id}/execution",
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": subscriber_a["license_key"],
            },
            json=payload,
        )

    db.expire_all()
    persisted = db.get(models.Command, command_id)
    execution = db.query(models.Execution).filter(
        models.Execution.command_id == command_id
    ).one_or_none()
    assert reported.status_code == 403, reported.text
    assert persisted.status == "SENT_TO_EA"
    assert persisted.account_id == account_b.id
    assert execution is None
    db.rollback()

    # Once the deliberate corruption is repaired, the original A receipt
    # remains possible; denying B's account must not erase broker truth.
    restored = db.get(models.Command, command_id)
    restored.account_id = account_a.id
    db.commit()
    db.rollback()
    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_k: None)
        rightful = client.post(
            f"/commands/{command_id}/execution",
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": subscriber_a["license_key"],
            },
            json=payload,
        )
    assert rightful.status_code == 200, rightful.text
    db.expire_all()
    assert db.get(models.Command, command_id).status == "FAILED"
    assert (
        db.query(models.Execution)
        .filter(models.Execution.command_id == command_id)
        .count()
    ) == 1
