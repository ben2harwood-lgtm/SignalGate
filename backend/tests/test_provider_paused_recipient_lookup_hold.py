"""Demo-only release HOLD: generic provider recipient lookup after pause.

The source-bound Telegram endpoint already refuses paused provider/feed scopes.
This distinct authenticated provider endpoint has no equivalent pause check.
These synthetic tests document the discrepancy without sending Telegram,
creating commands, contacting MT5, or changing the implementation.

Strict XFAIL is intentionally not a passing safety claim. A correction should
make these tests XPASS/CI-red until the owner removes the marker after review.
"""
from __future__ import annotations

import pytest

from app import crud, models, security

from .conftest import register_user
from .test_provider_tenancy import _headers, _provider_fixture


class _PausedProviderRecipientEnumeration(AssertionError):
    """Known policy discrepancy: paused scope still returns recipient IDs."""


@pytest.mark.parametrize("paused_scope_name", ("provider", "feed"))
@pytest.mark.xfail(
    strict=True,
    raises=_PausedProviderRecipientEnumeration,
    reason=(
        "RELEASE HOLD: generic provider /signals/recipients still enumerates "
        "subscribers after provider/feed pause; requires source-owner review"
    ),
)
def test_paused_provider_recipient_lookup_refuses_enumeration(
    client, db, paused_scope_name
):
    """Positive active control, then require a paused scope to fail closed.

    All identities are invented; this exercises only local FastAPI, an
    isolated test DB and provider-key auth, not Telegram delivery. The
    source-bound Telegram recipient path is covered in another test file.
    """
    provider, feed, raw_key = _provider_fixture(
        db, f"recipient-pause-hold-{paused_scope_name}"
    )
    telegram_id = "4671" if paused_scope_name == "provider" else "4672"
    user = register_user(
        client, telegram_id,
        f"recipient_pause_{paused_scope_name}",
        "Synthetic Subscriber",
    )
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, user["id"])
    )
    db.commit()

    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        def lookup():
            return client.get(
                "/signals/recipients",
                params={"feed_id": feed.id},
                headers=_headers(provider, raw_key),
            )

        active = lookup()
        assert active.status_code == 200, active.text
        assert [
            row["telegram_user_id"] for row in active.json()["recipients"]
        ] == [telegram_id], "Active positive control did not enumerate the feed"

        target = provider if paused_scope_name == "provider" else feed
        target.paused = True
        db.commit()
        db.expire_all()
        current = db.get(type(target), target.id)
        assert current is not None
        assert current.status == "ACTIVE" and current.paused is True

        paused_response = lookup()
        # Check these invariants on the actual expected-failure path too.
        # A strict XFAIL raised below must never mask an execution side effect.
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
        # Only the *observed* 200 + exact scoped subscriber leak is the
        # documented XFAIL. Unexpected 4xx/5xx, missing data or broader
        # enumeration must fail CI rather than masquerade as the known gap.
        if paused_response.status_code == 200:
            leaked = paused_response.json().get("recipients")
            assert isinstance(leaked, list)
            assert [(row["user_id"], row["telegram_user_id"]) for row in leaked] == [
                (user["id"], telegram_id)
            ], "Unexpected paused recipient payload, not the known policy gap"
            raise _PausedProviderRecipientEnumeration(
                "Paused generic provider recipient endpoint enumerated "
                f"the exact synthetic subscriber: scope={paused_scope_name}"
            )
        assert paused_response.status_code == 403, paused_response.text
        assert "recipients" not in paused_response.json()
        assert "paused" in paused_response.json().get("detail", "").lower()
    finally:
        security.settings.require_license = original_license_setting

@pytest.mark.parametrize("paused_scope_name", ("provider", "feed"))
def test_paused_scope_does_not_hide_unaffected_recipient_feeds(
    client, db, paused_scope_name
):
    """A pause must not hide an active sibling feed or unrelated provider.

    Positive tenant-scope guard for the eventual paused-recipient fix; no bot,
    broker, external provider, or executable command is involved.
    """
    target_provider, target_feed, target_key = _provider_fixture(
        db, f"pause-isolation-{paused_scope_name}"
    )
    if paused_scope_name == "provider":
        other_provider, other_feed, other_key = _provider_fixture(
            db, "pause-isolation-independent"
        )
    else:
        other_provider, other_key = target_provider, target_key
        # Complete HTTP registration before the fixture session has pending
        # writes, to avoid a SQLite cross-session lock on synthetic users.
        other_feed = None

    target_user = register_user(
        client, "4673" if paused_scope_name == "provider" else "4675",
        f"paused_isolation_target_{paused_scope_name}", "Synthetic Target",
    )
    other_telegram_id = "4674" if paused_scope_name == "provider" else "4676"
    other_user = register_user(
        client, other_telegram_id,
        f"paused_isolation_other_{paused_scope_name}", "Synthetic Unaffected",
    )
    if other_feed is None:
        other_feed = crud.create_feed(
            db, target_provider, "unpaused sibling", "pause-isolation-sibling"
        )
    crud.subscribe_user_to_feed(
        db, target_provider, target_feed,
        db.get(models.User, target_user["id"]),
    )
    crud.subscribe_user_to_feed(
        db, other_provider, other_feed,
        db.get(models.User, other_user["id"]),
    )
    db.commit()

    target = target_provider if paused_scope_name == "provider" else target_feed
    target.paused = True
    db.commit()
    db.expire_all()
    assert db.get(type(target), target.id).paused is True
    assert db.get(models.Provider, other_provider.id).paused is False
    assert db.get(models.Feed, other_feed.id).paused is False

    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        unaffected = client.get(
            "/signals/recipients",
            params={"feed_id": other_feed.id},
            headers=_headers(other_provider, other_key),
        )
        assert unaffected.status_code == 200, unaffected.text
        assert unaffected.json()["recipients"] == [{
            "user_id": other_user["id"],
            "telegram_user_id": other_telegram_id,
        }]
        if paused_scope_name == "provider":
            # Even the paused provider's valid key must not cross tenants.
            cross_tenant = client.get(
                "/signals/recipients",
                params={"feed_id": other_feed.id},
                headers=_headers(target_provider, target_key),
            )
            assert cross_tenant.status_code == 404, cross_tenant.text
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
    finally:
        security.settings.require_license = original_license_setting


def test_active_empty_feed_remains_queryable(client, db):
    """Do not fix paused-empty lookup by rejecting every empty feed.

    A valid, unpaused provider's empty feed has no recipients but should still
    return the normal successful empty result. Synthetic, offline and no trade.
    """
    provider, feed, raw_key = _provider_fixture(
        db, "recipient-pause-active-empty-control"
    )
    assert provider.status == "ACTIVE" and provider.paused is False
    assert feed.status == "ACTIVE" and feed.paused is False

    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        response = client.get(
            "/signals/recipients",
            params={"feed_id": feed.id},
            headers=_headers(provider, raw_key),
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"recipients": []}
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
    finally:
        security.settings.require_license = original_license_setting


@pytest.mark.parametrize("paused_scope_name", ("provider", "feed"))
@pytest.mark.xfail(
    strict=True,
    raises=_PausedProviderRecipientEnumeration,
    reason=(
        "RELEASE HOLD: paused /signals/recipients returns HTTP 200 even "
        "for an empty subscriber feed; pause denial must not depend on "
        "whether recipients happen to exist"
    ),
)
def test_paused_empty_feed_refuses_recipient_lookup(client, db, paused_scope_name):
    """Paused feed/provider must fail closed even without subscribers.

    Synthetic empty feed, isolated DB, no Telegram/broker/command. The
    source-owner fix must enforce pause before enumerating users; checking
    only whether the recipient list is nonempty is insufficient.
    """
    provider, feed, raw_key = _provider_fixture(
        db, f"recipient-pause-empty-{paused_scope_name}"
    )
    target = provider if paused_scope_name == "provider" else feed
    target.paused = True
    db.commit()
    db.expire_all()
    current = db.get(type(target), target.id)
    assert current is not None
    assert current.status == "ACTIVE" and current.paused is True

    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        response = client.get(
            "/signals/recipients",
            params={"feed_id": feed.id},
            headers=_headers(provider, raw_key),
        )
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
        if response.status_code == 200:
            assert response.json() == {"recipients": []}, (
                "Unexpected paused empty-feed payload, not the known policy gap"
            )
            raise _PausedProviderRecipientEnumeration(
                f"Paused empty {paused_scope_name} scope returned HTTP 200"
            )
        assert response.status_code == 403, response.text
        assert "recipients" not in response.json()
        assert "paused" in response.json().get("detail", "").lower()
    finally:
        security.settings.require_license = original_license_setting


class _InactiveFeedRecipientEnumeration(AssertionError):
    """Known policy discrepancy: non-ACTIVE feed still exposes recipients."""


@pytest.mark.xfail(
    strict=True,
    raises=_InactiveFeedRecipientEnumeration,
    reason=(
        "RELEASE HOLD: generic provider /signals/recipients still enumerates "
        "subscribers when the feed status is not ACTIVE; source-owner review"
    ),
)
def test_inactive_feed_refuses_recipient_lookup(client, db):
    """A disabled feed is not made eligible by a valid provider credential.

    This is an offline, invented-identity regression. Source-bound Telegram
    lookup already filters non-ACTIVE feed state. The provider principal remains
    ACTIVE; only the feed is disabled to isolate the missing state gate.
    """
    provider, feed, raw_key = _provider_fixture(db, "recipient-inactive-feed")
    user = register_user(
        client, "4681", "inactive_feed_subscriber", "Synthetic Subscriber",
    )
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, user["id"])
    )
    db.commit()

    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        def lookup():
            return client.get(
                "/signals/recipients",
                params={"feed_id": feed.id},
                headers=_headers(provider, raw_key),
            )

        active = lookup()
        assert active.status_code == 200, active.text
        assert active.json()["recipients"] == [{
            "user_id": user["id"],
            "telegram_user_id": "4681",
        }]

        feed.status = "INACTIVE"
        db.commit()
        db.expire_all()
        assert db.get(models.Feed, feed.id).status == "INACTIVE"
        assert db.get(models.Provider, provider.id).status == "ACTIVE"

        response = lookup()
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
        if response.status_code == 200:
            assert response.json() == {"recipients": [{
                "user_id": user["id"],
                "telegram_user_id": "4681",
            }]}, "Unexpected inactive-feed payload, not the known policy gap"
            raise _InactiveFeedRecipientEnumeration(
                "Non-ACTIVE feed still exposed the exact synthetic recipient"
            )
        assert response.status_code == 403, response.text
        assert "recipients" not in response.json()
        assert any(term in response.json().get("detail", "").lower()
                   for term in ("inactive", "not active", "disabled"))
    finally:
        security.settings.require_license = original_license_setting


@pytest.mark.xfail(
    strict=True,
    raises=_InactiveFeedRecipientEnumeration,
    reason=(
        "RELEASE HOLD: a non-ACTIVE empty feed still receives an HTTP 200 "
        "recipient lookup response; deny before subscriber enumeration"
    ),
)
def test_inactive_empty_feed_refuses_recipient_lookup(client, db):
    """Inactive feed denial must not depend on having any subscribers.

    Synthetic offline counterpart to the inactive-feed subscribed regression.
    The active empty baseline must remain accessible, while the same feed
    after deactivation must fail closed without trading side effects.
    """
    provider, feed, raw_key = _provider_fixture(
        db, "recipient-inactive-empty-feed"
    )
    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        def lookup():
            return client.get(
                "/signals/recipients",
                params={"feed_id": feed.id},
                headers=_headers(provider, raw_key),
            )

        active = lookup()
        assert active.status_code == 200, active.text
        assert active.json() == {"recipients": []}

        feed.status = "INACTIVE"
        db.commit()
        db.expire_all()
        assert db.get(models.Feed, feed.id).status == "INACTIVE"
        assert db.get(models.Provider, provider.id).status == "ACTIVE"

        response = lookup()
        # Assert no execution side effects *before* the deliberate XFAIL.
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
        if response.status_code == 200:
            assert response.json() == {"recipients": []}, (
                "Unexpected inactive empty-feed payload, not the known gap"
            )
            raise _InactiveFeedRecipientEnumeration(
                "Inactive empty feed returned HTTP 200 to recipient lookup"
            )
        assert response.status_code == 403, response.text
        assert "recipients" not in response.json()
        assert any(
            word in response.json().get("detail", "").lower()
            for word in ("inactive", "not active", "disabled")
        )
    finally:
        security.settings.require_license = original_license_setting


@pytest.mark.parametrize(
    "restricted_state",
    ("provider_paused", "feed_paused", "feed_inactive"),
)
def test_restricted_feed_authentication_and_tenant_ownership_precede_denial(
    client, db, restricted_state
):
    """An eventual pause fix must not turn bad credentials or foreign feeds into 403.

    This positive security regression is synthetic and broker-free. The owner
    endpoint currently lacks pause enforcement; this test intentionally checks
    only independently required 401/404 precedence, not that known missing gate.
    """
    owner, feed, owner_key = _provider_fixture(
        db, f"recipient-precedence-owner-{restricted_state}"
    )
    foreign, _foreign_feed, foreign_key = _provider_fixture(
        db, f"recipient-precedence-foreign-{restricted_state}"
    )
    synthetic_user = register_user(
        client, "4691", f"precedence_{restricted_state}", "Synthetic Subscriber"
    )
    crud.subscribe_user_to_feed(
        db, owner, feed, db.get(models.User, synthetic_user["id"])
    )
    db.commit()

    if restricted_state == "provider_paused":
        owner.paused = True
    elif restricted_state == "feed_paused":
        feed.paused = True
    else:
        feed.status = "INACTIVE"
    db.commit()
    db.expire_all()

    assert (
        db.get(models.Provider, owner.id).paused is True
        if restricted_state == "provider_paused"
        else db.get(models.Feed, feed.id).paused is True
        if restricted_state == "feed_paused"
        else db.get(models.Feed, feed.id).status == "INACTIVE"
    )

    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        bad_credentials = (
            _headers(owner, owner_key + "-wrong"),
            {"X-Provider-Id": owner.id},  # Missing key, not local demo authority.
            _headers(foreign, owner_key),  # Valid key, forged provider identity.
        )
        for supplied_headers in bad_credentials:
            denied = client.get(
                "/signals/recipients",
                params={"feed_id": feed.id},
                headers=supplied_headers,
            )
            assert denied.status_code == 401, denied.text
            assert "recipients" not in denied.json()

        foreign_scope = client.get(
            "/signals/recipients",
            params={"feed_id": feed.id},
            headers=_headers(foreign, foreign_key),
        )
        # Ownership privacy precedes scope state: never reveal a paused or
        # inactive *foreign* feed exists by returning a distinguishable 403.
        assert foreign_scope.status_code == 404, foreign_scope.text
        assert "recipients" not in foreign_scope.json()
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
    finally:
        security.settings.require_license = original_license_setting


@pytest.mark.parametrize(
    "restricted_state",
    ("provider_paused", "feed_paused", "feed_inactive"),
)
def test_rotated_provider_key_stays_unauthorised_for_restricted_feed(
    client, db, restricted_state
):
    """A revoked key must fail authentication before a restricted-feed decision.

    Rotation must not resurrect a former credential when an owner later adds
    paused/inactive feed denial. This uses only invented users, an isolated DB
    and local HTTP; it does not exercise Telegram, brokers or trade execution.
    """
    provider, feed, old_key = _provider_fixture(
        db, f"recipient-revoked-precedence-{restricted_state}"
    )
    telegram_id = "4699"
    user = register_user(
        client, telegram_id, f"revoked_precedence_{restricted_state}",
        "Synthetic Subscriber",
    )
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, user["id"])
    )
    db.commit()

    original_license_setting = security.settings.require_license
    security.settings.require_license = True
    try:
        def lookup(key):
            return client.get(
                "/signals/recipients",
                params={"feed_id": feed.id},
                headers=_headers(provider, key),
            )

        before = lookup(old_key)
        assert before.status_code == 200, before.text
        expected = {"recipients": [{
            "user_id": user["id"], "telegram_user_id": telegram_id,
        }]}
        assert before.json() == expected

        _rotated, new_key = crud.rotate_provider_credential(db, provider)
        if restricted_state == "provider_paused":
            provider.paused = True
        elif restricted_state == "feed_paused":
            feed.paused = True
        else:
            feed.status = "INACTIVE"
        db.commit()
        db.expire_all()

        old_access = lookup(old_key)
        assert old_access.status_code == 401, old_access.text
        assert "recipients" not in old_access.json()

        # Only check the new credential once the feed is active again: the
        # restricted-path policy is a *separately held* expected failure.
        if restricted_state == "provider_paused":
            db.get(models.Provider, provider.id).paused = False
        elif restricted_state == "feed_paused":
            db.get(models.Feed, feed.id).paused = False
        else:
            db.get(models.Feed, feed.id).status = "ACTIVE"
        db.commit()
        db.expire_all()
        new_access = lookup(new_key)
        assert new_access.status_code == 200, new_access.text
        assert new_access.json() == expected
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
    finally:
        security.settings.require_license = original_license_setting
