"""Read-only tenant operational observations, independent of history pagination."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from . import crud, models


def provider_operations(db: Session, provider: models.Provider) -> dict:
    now = models.utcnow()
    cutoff = now - dt.timedelta(minutes=5)
    command, execution = models.Command, models.Execution
    joined = command.__table__.outerjoin(execution, execution.command_id == command.id)
    # Keep these accepted combinations aligned with crud._reconciliation_state.
    reconciled = or_(
        command.status.in_(["PENDING", "SENT_TO_EA"]),
        and_(command.status == "FAILED", execution.status == "FAILED"),
        and_(execution.status == "SUCCESS", command.status.in_([
            "FULLY_CLOSED", "EXECUTED_OPEN", "PARTIAL_TP1_DONE", "PARTIAL_TP2_DONE",
        ])),
    )
    # COALESCE is intentional: SQL NULL from a missing execution is unresolved.
    review_required = ~func.coalesce(reconciled, False)
    expired_pending = and_(command.status == "PENDING", command.expires_at <= now)
    stale_report = and_(
        command.status == "SENT_TO_EA",
        func.coalesce(command.sent_to_ea_at, command.created_at) <= cutoff,
    )
    attention = or_(review_required, expired_pending, stale_report)

    def count_where(condition) -> int:
        return int(db.scalar(select(func.count()).select_from(joined).where(
            command.provider_id == provider.id, condition,
        )) or 0)

    counts = {
        "review_required": count_where(review_required),
        "expired_pending": count_where(expired_pending),
        "awaiting_report_over_5_minutes": count_where(stale_report),
        "failed_commands": count_where(command.status == "FAILED"),
    }
    issue_count = count_where(attention)
    issues = db.execute(select(
        command.id, command.feed_id, command.status, command.created_at,
    ).select_from(joined).where(
        command.provider_id == provider.id, attention,
    ).order_by(command.created_at.asc(), command.id.asc()).limit(20)).all()
    feeds = crud.list_provider_feeds(db, provider.id)
    overview = crud.provider_overview(db, provider.id)
    observations = []
    if crud.is_admin_paused(db):
        observations.append("Platform is paused; new commands are blocked.")
    if provider.paused or provider.status != "ACTIVE":
        observations.append("Provider is paused or inactive; new commands are blocked.")
    if not feeds:
        observations.append("Create a feed and configure its policy while paused.")
    elif not any(not feed.paused and feed.status == "ACTIVE" for feed in feeds):
        observations.append("All feeds are paused or inactive; complete setup before resuming.")
    if not overview["active_subscribers"]:
        observations.append("No active subscriptions; invite a subscriber and obtain their consent.")
    if not overview["active_accounts"]:
        observations.append("No active trading accounts; verify subscriber demo-account onboarding.")
    if issue_count:
        observations.append("Review outstanding commands with the operator and broker evidence. Do not blindly resend.")
    return {
        "schema": "signalgate-provider-operations-v1",
        "observed_at_utc": now.replace(tzinfo=dt.timezone.utc).isoformat(),
        "demo_only_mode": crud.settings.demo_only_mode,
        "scope": "Operational observations only; not pilot, MT5, security or legal acceptance.",
        "report_wait_threshold_minutes": 5,
        "counts": counts,
        "attention_count": issue_count,
        "oldest_attention_commands": [{
            "command_id": row.id, "feed_id": row.feed_id,
            "status": row.status, "created_at": row.created_at,
        } for row in issues],
        "attention_commands_truncated": issue_count > len(issues),
        "observations": observations,
    }
