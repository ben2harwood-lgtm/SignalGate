"""Core data-access and business logic.

Route handlers stay thin; all safety-critical rules (idempotency, expiry,
admin pause, one-command-per-approval) live here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .config import get_settings
from .models import utcnow
from .parser import parse_signal

settings = get_settings()


# --- ID generation --------------------------------------------------------

_PREFIXES = {
    models.ProviderOrganization: "ORG",
    models.ProviderFeed: "FEED",
    models.ProviderCredential: "PKEY",
    models.FeedSubscription: "SUB",
    models.User: "USER",
    models.Signal: "SIG",
    models.Approval: "APP",
    models.Command: "CMD",
    models.Execution: "EXE",
    models.TradeManagementEvent: "MGT",
    models.PerformanceLedger: "LED",
    models.AuditLog: "AUD",
    models.Setting: "SET",
}


def _next_id(db: Session, model) -> str:
    """Generate a collision-resistant id.

    Local demo users retain USER-000001 style ids because the bundled EA/demo
    instructions rely on that convenience. Hosted mode and all safety-critical
    entities use unpredictable ids so command/signal ids are not enumerable and
    concurrent inserts do not derive the same id from a row count.
    """
    prefix = _PREFIXES[model]
    if model is models.User and not settings.require_license:
        count = db.scalar(select(func.count()).select_from(model)) or 0
        return f"{prefix}-{count + 1:06d}"
    return f"{prefix}-{secrets.token_hex(8).upper()}"


# --- Audit logging --------------------------------------------------------

def add_audit(
    db: Session,
    event_type: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> models.AuditLog:
    log = models.AuditLog(
        id=_next_id(db, models.AuditLog),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_json=json.dumps(payload, default=str) if payload else None,
    )
    db.add(log)
    db.flush()
    return log


# --- Settings -------------------------------------------------------------

def get_setting(db: Session, key: str, default: Optional[str] = None) -> Optional[str]:
    row = db.scalar(select(models.Setting).where(models.Setting.key == key))
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> models.Setting:
    row = db.scalar(select(models.Setting).where(models.Setting.key == key))
    if row:
        row.value = value
    else:
        row = models.Setting(id=_next_id(db, models.Setting), key=key, value=value)
        db.add(row)
    db.flush()
    return row


def is_admin_paused(db: Session) -> bool:
    return (get_setting(db, "admin_paused", "false") or "false").lower() == "true"


def get_setting_int(db: Session, key: str, default: int) -> int:
    raw = get_setting(db, key)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def get_setting_float(db: Session, key: str, default: float) -> float:
    raw = get_setting(db, key)
    try:
        return float(raw) if raw is not None else default
    except (ValueError, TypeError):
        return default


# --- Provider tenancy ------------------------------------------------------

def _provider_key_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def create_provider_organization(db: Session, name: str) -> models.ProviderOrganization:
    org = models.ProviderOrganization(
        id=_next_id(db, models.ProviderOrganization),
        name=name.strip(),
        status="ACTIVE",
    )
    db.add(org)
    db.flush()
    add_audit(db, "PROVIDER_ORG_CREATED", "provider_organization", org.id)
    return org


def create_provider_feed(
    db: Session,
    organization_id: str,
    name: str,
    source_namespace: str,
) -> models.ProviderFeed:
    org = db.get(models.ProviderOrganization, organization_id)
    if org is None or org.status != "ACTIVE":
        raise ValueError("Provider organization is missing or inactive")
    namespace = source_namespace.strip()
    if not namespace:
        raise ValueError("source_namespace is required")
    existing = db.scalar(
        select(models.ProviderFeed).where(models.ProviderFeed.source_namespace == namespace)
    )
    if existing is not None:
        raise ValueError("source_namespace is already assigned to a feed")
    feed = models.ProviderFeed(
        id=_next_id(db, models.ProviderFeed),
        organization_id=organization_id,
        name=name.strip(),
        source_namespace=namespace,
        status="ACTIVE",
        paused=False,
    )
    db.add(feed)
    db.flush()
    add_audit(
        db,
        "PROVIDER_FEED_CREATED",
        "provider_feed",
        feed.id,
        {"organization_id": organization_id},
    )
    return feed


def issue_provider_credential(
    db: Session,
    organization_id: str,
    role: str = "OPERATOR",
) -> tuple[models.ProviderCredential, str]:
    org = db.get(models.ProviderOrganization, organization_id)
    if org is None or org.status != "ACTIVE":
        raise ValueError("Provider organization is missing or inactive")
    normalized_role = role.strip().upper()
    if normalized_role not in {"OPERATOR", "VIEWER"}:
        raise ValueError("Provider credential role must be OPERATOR or VIEWER")
    for _ in range(10):
        secret = "SGP_" + secrets.token_urlsafe(32)
        digest = _provider_key_hash(secret)
        if db.scalar(
            select(models.ProviderCredential).where(
                models.ProviderCredential.key_hash == digest
            )
        ) is None:
            break
    else:
        raise RuntimeError("Could not generate a unique provider credential")
    credential = models.ProviderCredential(
        id=_next_id(db, models.ProviderCredential),
        organization_id=organization_id,
        key_hash=digest,
        key_prefix=secret[:12],
        role=normalized_role,
        status="ACTIVE",
    )
    db.add(credential)
    db.flush()
    add_audit(
        db,
        "PROVIDER_CREDENTIAL_ISSUED",
        "provider_credential",
        credential.id,
        {"organization_id": organization_id, "role": normalized_role},
    )
    return credential, secret


def resolve_provider_credential(
    db: Session, secret: str
) -> Optional[models.ProviderCredential]:
    if not secret:
        return None
    digest = _provider_key_hash(secret)
    credential = db.scalar(
        select(models.ProviderCredential).where(
            models.ProviderCredential.key_hash == digest,
            models.ProviderCredential.status == "ACTIVE",
        )
    )
    if credential is None or not secrets.compare_digest(credential.key_hash, digest):
        return None
    org = db.get(models.ProviderOrganization, credential.organization_id)
    if org is None or org.status != "ACTIVE":
        return None
    credential.last_used_at = utcnow()
    db.flush()
    return credential


def list_provider_feeds(db: Session, organization_id: str) -> List[models.ProviderFeed]:
    return list(
        db.scalars(
            select(models.ProviderFeed)
            .where(models.ProviderFeed.organization_id == organization_id)
            .order_by(models.ProviderFeed.created_at.asc())
        ).all()
    )


def get_provider_feed(
    db: Session, organization_id: str, feed_id: str
) -> Optional[models.ProviderFeed]:
    return db.scalar(
        select(models.ProviderFeed).where(
            models.ProviderFeed.id == feed_id,
            models.ProviderFeed.organization_id == organization_id,
        )
    )


def get_provider_feed_by_source(
    db: Session, organization_id: str, source_namespace: str
) -> Optional[models.ProviderFeed]:
    return db.scalar(
        select(models.ProviderFeed).where(
            models.ProviderFeed.organization_id == organization_id,
            models.ProviderFeed.source_namespace == source_namespace,
        )
    )


def set_provider_feed_paused(
    db: Session, feed: models.ProviderFeed, paused: bool
) -> models.ProviderFeed:
    feed.paused = paused
    feed.updated_at = utcnow()
    db.flush()
    add_audit(
        db,
        "PROVIDER_FEED_PAUSED" if paused else "PROVIDER_FEED_RESUMED",
        "provider_feed",
        feed.id,
        {"organization_id": feed.organization_id},
    )
    return feed


def subscribe_user_to_feed(
    db: Session, feed: models.ProviderFeed, user: models.User
) -> models.FeedSubscription:
    existing = db.scalar(
        select(models.FeedSubscription).where(
            models.FeedSubscription.feed_id == feed.id,
            models.FeedSubscription.user_id == user.id,
        )
    )
    if existing is not None:
        existing.status = "ACTIVE"
        existing.updated_at = utcnow()
        db.flush()
        return existing
    subscription = models.FeedSubscription(
        id=_next_id(db, models.FeedSubscription),
        feed_id=feed.id,
        user_id=user.id,
        status="ACTIVE",
    )
    db.add(subscription)
    db.flush()
    add_audit(
        db,
        "FEED_SUBSCRIPTION_ACTIVATED",
        "feed_subscription",
        subscription.id,
        {"feed_id": feed.id, "user_id": user.id},
    )
    return subscription


def set_feed_subscription_status(
    db: Session, feed: models.ProviderFeed, user: models.User, status: str
) -> Optional[models.FeedSubscription]:
    subscription = db.scalar(
        select(models.FeedSubscription).where(
            models.FeedSubscription.feed_id == feed.id,
            models.FeedSubscription.user_id == user.id,
        )
    )
    if subscription is None:
        return None
    subscription.status = status
    subscription.updated_at = utcnow()
    db.flush()
    add_audit(
        db,
        "FEED_SUBSCRIPTION_STATUS_CHANGED",
        "feed_subscription",
        subscription.id,
        {"feed_id": feed.id, "user_id": user.id, "status": status},
    )
    return subscription


def is_user_subscribed_to_feed(db: Session, feed_id: str, user_id: str) -> bool:
    return db.scalar(
        select(models.FeedSubscription.id).where(
            models.FeedSubscription.feed_id == feed_id,
            models.FeedSubscription.user_id == user_id,
            models.FeedSubscription.status == "ACTIVE",
        )
    ) is not None


def list_active_feed_users(db: Session, feed_id: str) -> List[models.User]:
    return list(
        db.scalars(
            select(models.User)
            .join(models.FeedSubscription, models.FeedSubscription.user_id == models.User.id)
            .where(
                models.FeedSubscription.feed_id == feed_id,
                models.FeedSubscription.status == "ACTIVE",
                models.User.status == "ACTIVE",
            )
            .order_by(models.User.created_at.asc())
        ).all()
    )


# --- Users ----------------------------------------------------------------

def register_user(
    db: Session,
    telegram_user_id: str,
    telegram_username: Optional[str],
    first_name: Optional[str],
) -> models.User:
    user = db.scalar(
        select(models.User).where(
            models.User.telegram_user_id == str(telegram_user_id)
        )
    )
    if user:
        # Update lightweight profile fields.
        if telegram_username is not None:
            user.telegram_username = telegram_username
        if first_name is not None:
            user.first_name = first_name
        user.updated_at = utcnow()
        db.flush()
        add_audit(db, "USER_UPDATED", "user", user.id)
        return user

    user = models.User(
        id=_next_id(db, models.User),
        telegram_user_id=str(telegram_user_id),
        telegram_username=telegram_username,
        first_name=first_name,
        status="ACTIVE",
        fixed_lot_size=settings.default_lot_size,
        license_key=generate_license_key(),
    )
    db.add(user)
    db.flush()
    add_audit(db, "USER_REGISTERED", "user", user.id)
    return user


def get_user_by_telegram(db: Session, telegram_user_id: str) -> Optional[models.User]:
    return db.scalar(
        select(models.User).where(
            models.User.telegram_user_id == str(telegram_user_id)
        )
    )


def list_active_users(db: Session) -> List[models.User]:
    return list(
        db.scalars(
            select(models.User).where(models.User.status == "ACTIVE")
        ).all()
    )


def list_users(db: Session) -> List[models.User]:
    """All users (any status) for admin listing."""
    return list(
        db.scalars(select(models.User).order_by(models.User.created_at.asc())).all()
    )


# --- Licensing / customer activation (hosted multi-customer model) --------
#
# In the hosted deployment each paying customer is identified by a license
# key, which their MetaTrader EA presents on every request. The admin issues
# keys and can activate/deactivate a customer. Locally (REQUIRE_LICENSE off)
# none of this is required and the demo keeps working via the user_id path.

def generate_license_key() -> str:
    """Generate a human-readable, hard-to-guess license key, e.g. SG-AB12-CD34-EF56."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "SG-" + "-".join(groups)


def get_user_by_license(db: Session, license_key: str) -> Optional[models.User]:
    if not license_key:
        return None
    return db.scalar(
        select(models.User).where(models.User.license_key == license_key)
    )


def issue_license(db: Session, user: models.User) -> str:
    """Assign a fresh unique license key to a user and return it."""
    # Loop guards against the astronomically unlikely collision.
    for _ in range(10):
        key = generate_license_key()
        if get_user_by_license(db, key) is None:
            user.license_key = key
            user.updated_at = utcnow()
            db.flush()
            add_audit(db, "LICENSE_ISSUED", "user", user.id, {"rotated": True})
            return key
    raise RuntimeError("Could not generate a unique license key")


def set_user_status(db: Session, user: models.User, status: str) -> models.User:
    """Activate/deactivate/suspend a customer. Affects EA command delivery."""
    user.status = status
    user.updated_at = utcnow()
    db.flush()
    add_audit(db, "USER_STATUS_CHANGED", "user", user.id, {"status": status})
    return user


def resolve_ea_user(
    db: Session,
    user_id: Optional[str] = None,
    license_key: Optional[str] = None,
) -> Optional[models.User]:
    """Identify the customer an EA poll belongs to.

    Hosted mode (REQUIRE_LICENSE=true): the license key is the only accepted
    identifier; it must resolve to an ACTIVE customer.

    Local/demo mode (default): prefer the license key if it resolves, but fall
    back to user_id so the existing local EA (which sends a placeholder license)
    keeps working unchanged.
    """
    if license_key:
        user = get_user_by_license(db, license_key)
        if user is not None and user.status == "ACTIVE":
            return user
        # License did not resolve to an active customer.
        if settings.require_license:
            return None
        # else: fall through to the local user_id path below.

    if settings.require_license:
        return None  # hosted mode requires a valid license; none was usable.

    if user_id:
        user = db.get(models.User, user_id)
        if user is not None and user.status == "ACTIVE":
            return user
    return None


# --- Signals --------------------------------------------------------------

class SignalReplayConflict(ValueError):
    """Same provider-source message id was reused with different content."""


def create_signal(
    db: Session,
    raw_text: str,
    source: str = "TELEGRAM_ADMIN_TEST",
    source_message_id: Optional[str] = None,
    feed_id: Optional[str] = None,
) -> models.Signal:
    """Store + deterministically parse a signal. Always creates a ledger row."""
    from . import ledger  # local import to avoid cycle

    # Deduplicate provider/webhook retries before parsing/broadcast. Returning
    # the original Signal means downstream per-user approval idempotency still
    # guarantees at most one command for that source message.
    if source_message_id:
        existing = db.scalar(
            select(models.Signal).where(
                models.Signal.source == source,
                models.Signal.source_message_id == source_message_id,
            )
        )
        if existing is not None:
            if existing.raw_text != raw_text:
                add_audit(
                    db,
                    "SIGNAL_REPLAY_CONFLICT",
                    "signal",
                    existing.id,
                    {"source": source, "source_message_id": source_message_id},
                )
                raise SignalReplayConflict(
                    "Source message id was already used with different signal content"
                )
            add_audit(
                db,
                "SIGNAL_REPLAY_IGNORED",
                "signal",
                existing.id,
                {"source": source, "source_message_id": source_message_id},
            )
            return existing

    expiry_minutes = get_setting_int(
        db, "default_signal_expiry_minutes", settings.default_signal_expiry_minutes
    )
    parsed = parse_signal(raw_text, expiry_minutes=expiry_minutes)

    signal = models.Signal(
        id=_next_id(db, models.Signal),
        feed_id=feed_id,
        source=source,
        source_message_id=source_message_id,
        raw_text=raw_text,
        symbol=parsed.symbol,
        direction=parsed.direction,
        entry_type=parsed.entry_type,
        entry_price=parsed.entry_price,
        initial_stop_loss=parsed.initial_stop_loss,
        tp1=parsed.tp1,
        tp2=parsed.tp2,
        tp3=parsed.tp3,
        parser_status=parsed.parser_status,
        parser_error=parsed.parser_error,
        expires_at=parsed.expires_at,
        status="VALID" if parsed.is_valid else "REJECTED",
    )
    db.add(signal)
    try:
        db.flush()
    except IntegrityError:
        if not source_message_id:
            raise
        # Another worker may have inserted the same provider message after our
        # pre-check. Let the database uniqueness constraint arbitrate the race.
        db.rollback()
        existing = db.scalar(
            select(models.Signal).where(
                models.Signal.source == source,
                models.Signal.source_message_id == source_message_id,
            )
        )
        if existing is None:
            raise
        if existing.raw_text != raw_text:
            add_audit(
                db,
                "SIGNAL_REPLAY_CONFLICT",
                "signal",
                existing.id,
                {
                    "source": source,
                    "source_message_id": source_message_id,
                    "raced": True,
                },
            )
            raise SignalReplayConflict(
                "Source message id was already used with different signal content"
            )
        add_audit(
            db,
            "SIGNAL_REPLAY_IGNORED",
            "signal",
            existing.id,
            {"source": source, "source_message_id": source_message_id, "raced": True},
        )
        return existing

    add_audit(
        db,
        "SIGNAL_CREATED",
        "signal",
        signal.id,
        {"parser_status": parsed.parser_status, "error": parsed.parser_error},
    )

    # Every signal gets a performance ledger row, valid or not.
    ledger.create_ledger_for_signal(db, signal)
    return signal


def get_signal(db: Session, signal_id: str) -> Optional[models.Signal]:
    return db.get(models.Signal, signal_id)


def recent_signals(db: Session, limit: int = 20) -> List[models.Signal]:
    return list(
        db.scalars(
            select(models.Signal)
            .order_by(models.Signal.created_at.desc())
            .limit(limit)
        ).all()
    )


def _is_expired(expires_at: Optional[dt.datetime]) -> bool:
    if expires_at is None:
        return False
    return utcnow() > expires_at


def refresh_signal_expiry(db: Session, signal: models.Signal) -> None:
    """Mark a VALID signal EXPIRED if its time has passed."""
    if signal.status == "VALID" and _is_expired(signal.expires_at):
        signal.status = "EXPIRED"
        db.flush()
        add_audit(db, "SIGNAL_EXPIRED", "signal", signal.id)


# --- Approvals & commands -------------------------------------------------

def _existing_approval(
    db: Session, signal_id: str, user_id: str
) -> Optional[models.Approval]:
    return db.scalar(
        select(models.Approval).where(
            models.Approval.signal_id == signal_id,
            models.Approval.user_id == user_id,
        )
    )


def _command_for_approval(
    db: Session, approval_id: str
) -> Optional[models.Command]:
    return db.scalar(
        select(models.Command).where(models.Command.approval_id == approval_id)
    )


def approve_signal(
    db: Session, signal_id: str, telegram_user_id: str
) -> dict:
    """Process a YES decision.

    Returns a dict with keys: result, message, approval_id, command_id,
    duplicate. Enforces every safety rule before creating exactly one command.
    """
    from . import ledger

    user = get_user_by_telegram(db, telegram_user_id)
    if user is None:
        return _decision_result("USER_NOT_FOUND", "User not registered.")
    if user.status != "ACTIVE":
        return _decision_result("USER_INACTIVE", "User is not active.")

    signal = get_signal(db, signal_id)
    if signal is None:
        return _decision_result("SIGNAL_NOT_FOUND", "Signal not found.")

    # SAFETY: a duplicate decision must never create a second command.
    existing = _existing_approval(db, signal.id, user.id)
    if existing is not None:
        cmd = _command_for_approval(db, existing.id)
        if existing.decision == "YES":
            if cmd is None:
                return _decision_result(
                    "ALREADY_BLOCKED",
                    "Earlier approval was blocked; no command was created.",
                    approval_id=existing.id,
                    duplicate=True,
                )
            return _decision_result(
                "ALREADY_APPROVED",
                "Already approved. No duplicate command created.",
                approval_id=existing.id,
                command_id=cmd.id,
                duplicate=True,
            )
        # First decision was NO -> first decision wins for v1.
        return _decision_result(
            "ALREADY_REJECTED",
            "Already rejected earlier. First decision wins; no command created.",
            approval_id=existing.id,
            duplicate=True,
        )

    # TENANCY: tenant-bound signals may only create commands for active
    # subscribers of their owning feed, and provider pause is fail-closed.
    if signal.feed_id is not None:
        feed = db.get(models.ProviderFeed, signal.feed_id)
        if feed is None or feed.status != "ACTIVE":
            approval = _record_approval(db, signal, user, "YES", "BLOCKED")
            add_audit(db, "APPROVAL_BLOCKED_FEED_INACTIVE", "approval", approval.id)
            return _decision_result(
                "FEED_INACTIVE",
                "Provider feed is inactive. No command created.",
                approval_id=approval.id,
            )
        if feed.paused:
            approval = _record_approval(db, signal, user, "YES", "BLOCKED")
            add_audit(db, "APPROVAL_BLOCKED_FEED_PAUSED", "approval", approval.id)
            return _decision_result(
                "FEED_PAUSED",
                "Provider feed is paused. No command created.",
                approval_id=approval.id,
            )
        if not is_user_subscribed_to_feed(db, feed.id, user.id):
            approval = _record_approval(db, signal, user, "YES", "BLOCKED")
            add_audit(
                db,
                "APPROVAL_BLOCKED_NOT_SUBSCRIBED",
                "approval",
                approval.id,
                {"feed_id": feed.id, "user_id": user.id},
            )
            return _decision_result(
                "NOT_SUBSCRIBED",
                "User is not subscribed to this provider feed.",
                approval_id=approval.id,
            )

    # SAFETY: admin pause blocks command creation.
    if is_admin_paused(db):
        approval = _record_approval(db, signal, user, "YES", "BLOCKED")
        add_audit(db, "APPROVAL_BLOCKED_PAUSE", "approval", approval.id)
        return _decision_result(
            "TRADING_PAUSED",
            "Trading paused. No command created.",
            approval_id=approval.id,
        )

    # SAFETY: only VALID signals can be approved.
    if signal.parser_status != "VALID":
        approval = _record_approval(db, signal, user, "YES", "REJECTED")
        return _decision_result(
            "PARSER_REJECTED",
            "Parser rejected signal. No command created.",
            approval_id=approval.id,
        )

    # SAFETY: expired signals must not create commands.
    refresh_signal_expiry(db, signal)
    if signal.status == "EXPIRED" or _is_expired(signal.expires_at):
        signal.status = "EXPIRED"
        approval = _record_approval(db, signal, user, "YES", "EXPIRED")
        return _decision_result(
            "SIGNAL_EXPIRED",
            "Signal expired. No command created.",
            approval_id=approval.id,
        )

    # All checks passed -> create approval + exactly one command.
    approval = _record_approval(db, signal, user, "YES", "APPROVED")
    command = _create_command(db, signal, approval, user)
    add_audit(
        db, "COMMAND_CREATED", "command", command.id, {"signal_id": signal.id}
    )
    ledger.on_command_created(db, signal, command)

    return _decision_result(
        "APPROVED",
        "Approved. Waiting for MetaTrader EA to execute demo trade.",
        approval_id=approval.id,
        command_id=command.id,
    )


def reject_signal(
    db: Session, signal_id: str, telegram_user_id: str
) -> dict:
    """Process a NO decision. Creates no command; idempotent."""
    from . import ledger

    user = get_user_by_telegram(db, telegram_user_id)
    if user is None:
        return _decision_result("USER_NOT_FOUND", "User not registered.")

    signal = get_signal(db, signal_id)
    if signal is None:
        return _decision_result("SIGNAL_NOT_FOUND", "Signal not found.")

    existing = _existing_approval(db, signal.id, user.id)
    if existing is not None:
        if existing.decision == "NO":
            return _decision_result(
                "ALREADY_REJECTED",
                "Already rejected. No trade command created.",
                approval_id=existing.id,
                duplicate=True,
            )
        cmd = _command_for_approval(db, existing.id)
        return _decision_result(
            "ALREADY_APPROVED",
            "Already approved earlier. First decision wins.",
            approval_id=existing.id,
            command_id=cmd.id if cmd else None,
            duplicate=True,
        )

    approval = _record_approval(db, signal, user, "NO", "REJECTED")
    add_audit(db, "SIGNAL_REJECTED", "approval", approval.id)
    ledger.on_rejected(db, signal)
    return _decision_result(
        "REJECTED",
        "Rejected. No trade command created.",
        approval_id=approval.id,
    )


def _record_approval(
    db: Session,
    signal: models.Signal,
    user: models.User,
    decision: str,
    status: str,
) -> models.Approval:
    approval = models.Approval(
        id=_next_id(db, models.Approval),
        signal_id=signal.id,
        user_id=user.id,
        decision=decision,
        status=status,
    )
    db.add(approval)
    db.flush()
    add_audit(
        db,
        "APPROVAL_RECORDED",
        "approval",
        approval.id,
        {"decision": decision, "status": status},
    )
    return approval


def _create_command(
    db: Session,
    signal: models.Signal,
    approval: models.Approval,
    user: models.User,
) -> models.Command:
    """Create exactly one command from an approved valid signal."""
    expiry_minutes = get_setting_int(
        db, "default_signal_expiry_minutes", settings.default_signal_expiry_minutes
    )
    split_mode = (
        get_setting(db, "split_ticket_demo_partial_mode", "true") or "true"
    ).lower() == "true"

    command = models.Command(
        id=_next_id(db, models.Command),
        signal_id=signal.id,
        approval_id=approval.id,
        user_id=user.id,
        symbol=signal.symbol,
        direction=signal.direction,
        entry_type=signal.entry_type or "MARKET",
        entry_price=signal.entry_price,
        initial_stop_loss=signal.initial_stop_loss,
        tp1=signal.tp1,
        tp2=signal.tp2,
        tp3=signal.tp3,
        tp1_close_percent=get_setting_int(db, "tp1_close_percent", 50),
        tp2_close_percent=get_setting_int(db, "tp2_close_percent", 25),
        tp3_close_percent=get_setting_int(db, "tp3_close_percent", 25),
        lot_size=get_setting_float(db, "default_lot_size", settings.default_lot_size),
        split_ticket_demo_partial_mode=split_mode,
        tp1_lot=get_setting_float(db, "tp1_lot", settings.tp1_lot),
        tp2_lot=get_setting_float(db, "tp2_lot", settings.tp2_lot),
        tp3_lot=get_setting_float(db, "tp3_lot", settings.tp3_lot),
        risk_percent=user.risk_percent,
        status="PENDING",
        expires_at=utcnow() + dt.timedelta(minutes=expiry_minutes),
    )
    db.add(command)
    db.flush()
    return command


# --- EA command polling ---------------------------------------------------

def get_pending_command_for_user(
    db: Session, user_id: str
) -> Optional[models.Command]:
    """Atomically claim the oldest pending non-expired command for a user.

    PostgreSQL uses SELECT ... FOR UPDATE SKIP LOCKED so two EA polls/workers
    cannot claim the same command concurrently. SQLite keeps the simple local
    demo path, where the test/demo process is single-worker.
    """
    while True:
        query = (
            select(models.Command)
            .where(
                models.Command.user_id == user_id,
                models.Command.status == "PENDING",
            )
            .order_by(models.Command.created_at.asc())
            .limit(1)
        )
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)

        command = db.scalar(query)
        if command is None:
            return None

        if _is_expired(command.expires_at):
            command.status = "EXPIRED"
            db.flush()
            add_audit(db, "COMMAND_EXPIRED", "command", command.id)
            continue

        command.status = "SENT_TO_EA"
        command.sent_to_ea_at = utcnow()
        db.flush()
        add_audit(db, "COMMAND_SENT_TO_EA", "command", command.id)
        return command


def get_command(db: Session, command_id: str) -> Optional[models.Command]:
    return db.get(models.Command, command_id)


def recent_commands(db: Session, limit: int = 20) -> List[models.Command]:
    return list(
        db.scalars(
            select(models.Command)
            .order_by(models.Command.created_at.desc())
            .limit(limit)
        ).all()
    )


def mark_command_received(db: Session, command: models.Command) -> None:
    add_audit(db, "COMMAND_RECEIVED_BY_EA", "command", command.id)


# --- Executions -----------------------------------------------------------

class ExecutionReportConflict(ValueError):
    """A retry disagrees with the already-recorded broker execution outcome."""


_EXECUTION_REPORT_FIELDS = (
    "status",
    "broker_ticket",
    "child_tickets_json",
    "executed_symbol",
    "executed_direction",
    "requested_price",
    "executed_price",
    "lot_size",
    "initial_stop_loss",
    "tp1",
    "tp2",
    "tp3",
    "spread_at_execution",
    "slippage",
    "error_code",
    "error_message",
)


def _execution_report_mismatches(
    existing: models.Execution, payload
) -> list[str]:
    return [
        field
        for field in _EXECUTION_REPORT_FIELDS
        if getattr(existing, field) != getattr(payload, field)
    ]


def _existing_execution_or_conflict(
    db: Session,
    command: models.Command,
    existing: models.Execution,
    payload,
    *,
    raced: bool = False,
) -> tuple[models.Execution, bool]:
    mismatches = _execution_report_mismatches(existing, payload)
    if mismatches:
        add_audit(
            db,
            "EXECUTION_REPORT_CONFLICT",
            "command",
            command.id,
            {
                "execution_id": existing.id,
                "mismatched_fields": mismatches,
                "existing_status": existing.status,
                "incoming_status": payload.status,
                "raced": raced,
            },
        )
        raise ExecutionReportConflict(
            "Conflicting execution report for command; manual reconciliation required"
        )

    add_audit(
        db,
        "DUPLICATE_EXECUTION_REPORT_IGNORED",
        "command",
        command.id,
        {"execution_id": existing.id, "raced": raced},
    )
    return existing, False


def record_execution(
    db: Session, command: models.Command, payload
) -> tuple[models.Execution, bool]:
    """Record an execution result exactly once.

    EA/network retries are normal. A retry for a command that already has an
    execution returns the original row and does not replay ledger/state changes.
    """
    from . import ledger

    existing = db.scalar(
        select(models.Execution).where(models.Execution.command_id == command.id)
    )
    if existing is not None:
        return _existing_execution_or_conflict(db, command, existing, payload)

    if command.status in {"FULLY_CLOSED", "FAILED", "EXPIRED"}:
        raise ValueError(f"Cannot report execution for terminal command {command.status}")

    execution = models.Execution(
        id=_next_id(db, models.Execution),
        command_id=command.id,
        user_id=command.user_id,
        status=payload.status,
        broker_ticket=payload.broker_ticket,
        child_tickets_json=payload.child_tickets_json,
        executed_symbol=payload.executed_symbol,
        executed_direction=payload.executed_direction,
        requested_price=payload.requested_price,
        executed_price=payload.executed_price,
        lot_size=payload.lot_size,
        initial_stop_loss=payload.initial_stop_loss,
        tp1=payload.tp1,
        tp2=payload.tp2,
        tp3=payload.tp3,
        spread_at_execution=payload.spread_at_execution,
        slippage=payload.slippage,
        error_code=payload.error_code,
        error_message=payload.error_message,
    )
    db.add(execution)

    if payload.status == "SUCCESS":
        command.status = "EXECUTED_OPEN"
        command.processed_at = utcnow()
    else:
        command.status = "FAILED"
        command.last_error = payload.error_message or payload.error_code
        command.processed_at = utcnow()

    try:
        db.flush()
    except IntegrityError:
        # A simultaneous retry may have won the unique(command_id) race after
        # our initial lookup. Roll back this transaction and return the winner.
        db.rollback()
        existing = db.scalar(
            select(models.Execution).where(models.Execution.command_id == command.id)
        )
        if existing is not None:
            return _existing_execution_or_conflict(
                db, command, existing, payload, raced=True
            )
        raise

    add_audit(
        db,
        "EXECUTION_RECORDED",
        "execution",
        execution.id,
        {"status": payload.status, "command_id": command.id},
    )
    ledger.on_execution(db, command, execution)
    return execution, True


# --- Management events ----------------------------------------------------

class ManagementEventConflict(ValueError):
    """A retried lifecycle event disagrees with the stored event payload."""


_MANAGEMENT_EVENT_FIELDS = (
    "broker_ticket",
    "event_type",
    "stage",
    "requested_action",
    "result",
    "price",
    "lot_size_before",
    "lot_size_after",
    "stop_loss_before",
    "stop_loss_after",
    "error_code",
    "error_message",
)


def _management_event_mismatches(
    existing: models.TradeManagementEvent, payload
) -> list[str]:
    return [
        field
        for field in _MANAGEMENT_EVENT_FIELDS
        if getattr(existing, field) != getattr(payload, field)
    ]


def _existing_management_event_or_conflict(
    db: Session,
    command: models.Command,
    existing: models.TradeManagementEvent,
    payload,
    *,
    raced: bool = False,
) -> tuple[models.TradeManagementEvent, bool]:
    mismatches = _management_event_mismatches(existing, payload)
    if mismatches:
        add_audit(
            db,
            "MANAGEMENT_EVENT_CONFLICT",
            "command",
            command.id,
            {
                "event_id": existing.id,
                "event_type": payload.event_type,
                "mismatched_fields": mismatches,
                "raced": raced,
            },
        )
        raise ManagementEventConflict(
            "Conflicting management event retry; manual reconciliation required"
        )

    add_audit(
        db,
        "DUPLICATE_MANAGEMENT_EVENT_IGNORED",
        "command",
        command.id,
        {"event_id": existing.id, "event_type": payload.event_type, "raced": raced},
    )
    return existing, False


# Map of management event_type -> resulting command status (if any).
_EVENT_TO_COMMAND_STATUS = {
    "OPENED": "EXECUTED_OPEN",
    "TP1_CLOSE_SUCCESS": "PARTIAL_TP1_DONE",
    "TP2_CLOSE_SUCCESS": "PARTIAL_TP2_DONE",
    "TP3_CLOSE_SUCCESS": "FULLY_CLOSED",
    "FULLY_CLOSED": "FULLY_CLOSED",
    "STOP_LOSS_HIT": "FULLY_CLOSED",
    "FAILED_MANAGEMENT": "FAILED",
}


def _management_event_key(command: models.Command, payload) -> str:
    parts = [
        command.id,
        payload.event_type or "",
        payload.stage or "",
        payload.result or "",
        payload.broker_ticket or "",
        payload.requested_action or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def record_management_event(
    db: Session, command: models.Command, payload
) -> tuple[models.TradeManagementEvent, bool]:
    """Store a management event idempotently and advance state monotonically."""
    from . import ledger

    event_key = _management_event_key(command, payload)
    existing = db.scalar(
        select(models.TradeManagementEvent).where(
            models.TradeManagementEvent.idempotency_key == event_key
        )
    )
    if existing is not None:
        return _existing_management_event_or_conflict(
            db, command, existing, payload
        )

    event = models.TradeManagementEvent(
        id=_next_id(db, models.TradeManagementEvent),
        command_id=command.id,
        idempotency_key=event_key,
        broker_ticket=payload.broker_ticket,
        event_type=payload.event_type,
        stage=payload.stage,
        requested_action=payload.requested_action,
        result=payload.result,
        price=payload.price,
        lot_size_before=payload.lot_size_before,
        lot_size_after=payload.lot_size_after,
        stop_loss_before=payload.stop_loss_before,
        stop_loss_after=payload.stop_loss_after,
        error_code=payload.error_code,
        error_message=payload.error_message,
    )
    db.add(event)

    terminal = command.status in {"FULLY_CLOSED", "FAILED", "EXPIRED"}
    new_status = _EVENT_TO_COMMAND_STATUS.get(payload.event_type)
    if new_status and not terminal:
        command.status = new_status
        if new_status in {"FULLY_CLOSED", "FAILED"}:
            command.processed_at = utcnow()

    try:
        db.flush()
    except IntegrityError:
        # Same event raced us. The unique idempotency key makes the DB the
        # final arbiter even with multiple API workers.
        db.rollback()
        existing = db.scalar(
            select(models.TradeManagementEvent).where(
                models.TradeManagementEvent.idempotency_key == event_key
            )
        )
        if existing is not None:
            return _existing_management_event_or_conflict(
                db, command, existing, payload, raced=True
            )
        raise

    add_audit(
        db,
        "MANAGEMENT_EVENT",
        "management_event",
        event.id,
        {
            "event_type": payload.event_type,
            "command_id": command.id,
            "state_advanced": bool(new_status and not terminal),
        },
    )
    if not terminal:
        ledger.on_management_event(db, command, event)
    return event, True


# --- helpers --------------------------------------------------------------

def _decision_result(
    result: str,
    message: str,
    approval_id: Optional[str] = None,
    command_id: Optional[str] = None,
    duplicate: bool = False,
) -> dict:
    return {
        "result": result,
        "message": message,
        "approval_id": approval_id,
        "command_id": command_id,
        "duplicate": duplicate,
    }
