"""SQLAlchemy ORM models for SignalGate.

All timestamps are stored as UTC datetimes. String primary keys follow the
human-readable prefixed format (e.g. USER-000001) generated in crud.py.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> dt.datetime:
    """Single source of truth for current UTC time (naive UTC)."""
    return dt.datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    telegram_user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    risk_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fixed_lot_size: Mapped[float] = mapped_column(Float, default=0.01)
    # Per-customer license key (hosted model). Unique when set; many users may
    # have NULL locally (both SQLite and Postgres permit multiple NULLs here).
    license_key: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, default="TELEGRAM_ADMIN_TEST")
    source_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entry_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    initial_stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    parser_status: Mapped[str] = mapped_column(String, default="REJECTED")
    parser_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="NEW")
    edited_marker: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_marker: Mapped[bool] = mapped_column(Boolean, default=False)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("signal_id", "user_id", name="uq_signal_user_approval"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    decision: Mapped[str] = mapped_column(String)  # YES / NO
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    # APPROVED / REJECTED / DUPLICATE / EXPIRED / BLOCKED
    status: Mapped[str] = mapped_column(String)


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    entry_type: Mapped[str] = mapped_column(String)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    initial_stop_loss: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp1_close_percent: Mapped[int] = mapped_column(Integer, default=50)
    tp2_close_percent: Mapped[int] = mapped_column(Integer, default=25)
    tp3_close_percent: Mapped[int] = mapped_column(Integer, default=25)
    lot_size: Mapped[float] = mapped_column(Float, default=0.01)
    split_ticket_demo_partial_mode: Mapped[bool] = mapped_column(
        Boolean, default=True
    )
    tp1_lot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp2_lot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp3_lot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    sent_to_ea_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime, nullable=True
    )
    processed_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    command_id: Mapped[str] = mapped_column(ForeignKey("commands.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String)  # SUCCESS / FAILED
    broker_ticket: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    child_tickets_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executed_symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    executed_direction: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requested_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lot_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    initial_stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spread_at_execution: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    slippage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class TradeManagementEvent(Base):
    __tablename__ = "trade_management_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    command_id: Mapped[str] = mapped_column(ForeignKey("commands.id"), index=True)
    broker_ticket: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    event_type: Mapped[str] = mapped_column(String)
    stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requested_action: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lot_size_before: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lot_size_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss_before: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class PerformanceLedger(Base):
    __tablename__ = "performance_ledger"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    command_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("commands.id"), nullable=True, index=True
    )
    symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    initial_stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result_status: Mapped[str] = mapped_column(String, default="PENDING")
    r_result: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_favourable_excursion: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    max_adverse_excursion: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    signal_to_card_delay: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    approval_to_execution_delay: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    slippage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spread_at_execution: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    final_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String)
    entity_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True, index=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
