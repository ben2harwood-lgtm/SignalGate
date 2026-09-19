"""Pydantic request/response schemas."""
from __future__ import annotations

import datetime as dt
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Provider tenancy -----------------------------------------------------

class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")


class ProviderCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")


class FeedCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_namespace: str = Field(min_length=1, max_length=120)


class ProviderCredentialCreate(BaseModel):
    label: str = Field(default="default", min_length=1, max_length=80)


class ProviderCredentialOut(BaseModel):
    provider_id: str
    credential_id: str
    api_key: str
    label: str


class FeedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: str
    name: str
    source_namespace: str
    status: str
    paused: bool
    allowed_symbols_json: Optional[str] = None
    expiry_minutes: Optional[int] = None
    default_lot_size: Optional[float] = None


class FeedPolicyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    allowed_symbols: Optional[list[str]] = None
    expiry_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    default_lot_size: Optional[float] = Field(default=None, gt=0, le=100)


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    slug: str
    status: str
    paused: bool
    brand_display_name: Optional[str] = None
    brand_logo_url: Optional[str] = None
    brand_primary_color: Optional[str] = None
    support_contact: Optional[str] = None


class ProviderBrandingUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=120)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    primary_color: Optional[str] = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )
    support_contact: Optional[str] = Field(default=None, max_length=200)


class DemoTenantOut(BaseModel):
    provider_id: str
    provider_api_key: str
    feed_id: str
    user_id: str
    telegram_user_id: str
    license_key: Optional[str] = None


class SubscriptionInviteCreate(BaseModel):
    feed_id: str
    expires_minutes: int = Field(default=1440, ge=5, le=10080)


class SubscriptionInviteOut(BaseModel):
    invite_id: str
    feed_id: str
    status: str
    expires_at: dt.datetime
    accepted_user_id: Optional[str] = None
    invite_token: Optional[str] = None


class SubscriptionInviteAccept(BaseModel):
    invite_token: str = Field(min_length=20, max_length=200)
    telegram_user_id: str


class SubscriptionAcceptanceOut(BaseModel):
    subscription_id: str
    account_id: str
    provider_id: str
    provider_name: str
    provider_display_name: Optional[str] = None
    feed_id: str
    feed_name: str
    status: str


class SubscriptionCreate(BaseModel):
    feed_id: str
    telegram_user_id: str


class SubscriptionOut(BaseModel):
    subscription_id: str
    account_id: str
    feed_id: str
    user_id: str
    status: str


class ProviderOverview(BaseModel):
    provider: ProviderOut
    feed_count: int
    active_subscribers: int
    active_accounts: int
    signal_count: int
    command_count: int


# --- Users ----------------------------------------------------------------

class RegisterUserRequest(BaseModel):
    telegram_user_id: str
    telegram_username: Optional[str] = None
    first_name: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    telegram_user_id: str
    telegram_username: Optional[str] = None
    first_name: Optional[str] = None
    status: str
    fixed_lot_size: float
    license_key: Optional[str] = None
    license_key_last4: Optional[str] = None


# --- Signals --------------------------------------------------------------

class CreateSignalRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="TELEGRAM_ADMIN_TEST", min_length=1, max_length=100)
    source_message_id: Optional[str] = Field(default=None, max_length=200)
    feed_id: Optional[str] = Field(default=None, max_length=80)


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: Optional[str] = None
    feed_id: Optional[str] = None
    source: str
    raw_text: str
    symbol: Optional[str] = None
    direction: Optional[str] = None
    entry_type: Optional[str] = None
    entry_price: Optional[float] = None
    initial_stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    parser_status: str
    parser_error: Optional[str] = None
    status: str
    created_at: dt.datetime
    expires_at: Optional[dt.datetime] = None


# --- Approvals / decisions ------------------------------------------------

class DecisionRequest(BaseModel):
    telegram_user_id: str


class DecisionResponse(BaseModel):
    result: str  # human-readable outcome code
    message: str
    approval_id: Optional[str] = None
    command_id: Optional[str] = None
    duplicate: bool = False


# --- Commands -------------------------------------------------------------

class TakeProfitOut(BaseModel):
    level: int
    price: Optional[float] = None
    close_percent: int
    lot: Optional[float] = None
    move_sl_to: Optional[str] = None


class CommandOut(BaseModel):
    command_id: str
    signal_id: str
    approval_id: str
    user_id: str
    symbol: str
    direction: str
    entry_type: str
    entry_price: Optional[float] = None
    initial_stop_loss: float
    take_profits: List[TakeProfitOut]
    lot_size: float
    split_ticket_demo_partial_mode: bool
    expires_at: Optional[dt.datetime] = None
    demo_only: bool = True


class PendingCommandResponse(BaseModel):
    command: Optional[CommandOut] = None


# --- EA: received / execution / management --------------------------------

class CommandReceivedRequest(BaseModel):
    note: Optional[str] = None


class ExecutionRequest(BaseModel):
    status: Literal["SUCCESS", "FAILED"]
    broker_ticket: Optional[str] = None
    child_tickets_json: Optional[str] = None
    executed_symbol: Optional[str] = None
    executed_direction: Optional[str] = None
    requested_price: Optional[float] = None
    executed_price: Optional[float] = None
    lot_size: Optional[float] = None
    initial_stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    spread_at_execution: Optional[float] = None
    slippage: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class BrokerPositionReconcileRequest(BaseModel):
    broker_tickets: List[str] = Field(min_length=1, max_length=20)
    executed_symbol: str = Field(min_length=1, max_length=80)
    executed_direction: Literal["BUY", "SELL"]
    executed_price: float = Field(gt=0)
    lot_size: float = Field(gt=0)
    stop_loss: Optional[float] = Field(default=None, gt=0)


class BrokerPositionReconcileResponse(BaseModel):
    status: Literal["matched", "recovered"]
    execution_id: str
    command_status: str


class ManagementEventRequest(BaseModel):
    broker_ticket: Optional[str] = None
    event_type: Literal[
        "OPENED",
        "TP1_REACHED",
        "TP1_CLOSE_SUCCESS",
        "SL_MOVE_BREAKEVEN_SUCCESS",
        "SL_MOVE_BREAKEVEN_FAILED",
        "TP2_REACHED",
        "TP2_CLOSE_SUCCESS",
        "SL_MOVE_TP1_SUCCESS",
        "SL_MOVE_TP1_FAILED",
        "TP3_REACHED",
        "TP3_CLOSE_SUCCESS",
        "FULLY_CLOSED",
        "STOP_LOSS_HIT",
        "FAILED_MANAGEMENT",
    ]
    stage: Optional[str] = None
    requested_action: Optional[str] = None
    result: Optional[Literal["SUCCESS", "FAILED", "PENDING"]] = None
    price: Optional[float] = None
    lot_size_before: Optional[float] = None
    lot_size_after: Optional[float] = None
    stop_loss_before: Optional[float] = None
    stop_loss_after: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class ExtractionResponse(BaseModel):
    """Preview of a signal extracted from an uploaded image.

    The image is read into `extracted_text`, which is then run through the
    deterministic parser. Nothing is created or broadcast — the bot shows this
    back to the signal provider to confirm or edit first.
    """

    engine: str
    readable: bool
    confidence: str
    notes: Optional[str] = None
    extracted_text: str
    parser_status: str
    parser_error: Optional[str] = None
    symbol: Optional[str] = None
    direction: Optional[str] = None
    entry_type: Optional[str] = None
    entry_price: Optional[float] = None
    initial_stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None


class SimpleStatus(BaseModel):
    status: str = "ok"


class HealthResponse(BaseModel):
    status: str = "ok"
    demo_only_mode: bool
    admin_paused: bool


class ReadinessResponse(BaseModel):
    status: str = "ready"
    database: str = "ok"
