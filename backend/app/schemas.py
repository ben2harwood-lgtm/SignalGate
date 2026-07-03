"""Pydantic request/response schemas."""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


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


# --- Signals --------------------------------------------------------------

class CreateSignalRequest(BaseModel):
    raw_text: str
    source: str = "TELEGRAM_ADMIN_TEST"
    source_message_id: Optional[str] = None


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
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
    status: str  # SUCCESS / FAILED
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


class ManagementEventRequest(BaseModel):
    broker_ticket: Optional[str] = None
    event_type: str
    stage: Optional[str] = None
    requested_action: Optional[str] = None
    result: Optional[str] = None
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
