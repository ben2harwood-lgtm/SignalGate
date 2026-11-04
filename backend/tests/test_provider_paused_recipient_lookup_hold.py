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
        if (
            paused_response.status_code != 403
            or "recipients" in paused_response.json()
        ):
            raise _PausedProviderRecipientEnumeration(
                "Paused generic provider recipient endpoint enumerated "
                f"subscriber data: scope={paused_scope_name}, "
                f"HTTP={paused_response.status_code}, "
                f"recipient_key_present={'recipients' in paused_response.json()}"
            )
        assert "paused" in paused_response.json().get("detail", "").lower()
        assert db.query(models.Command).count() == 0
        assert db.query(models.Execution).count() == 0
    finally:
        security.settings.require_license = original_license_setting
