# SignalGate Architecture

SignalGate is a **demo-only** Telegram-to-MetaTrader 5 trade execution system.
A human approves each signal; only then does a single validated command reach
the trading terminal. Raw Telegram text never reaches MetaTrader.

## Components

```
┌──────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│ Telegram bot │ <-> │   FastAPI backend (SoT)   │ <-> │  MT5 EA /    │
│ (PTB client) │HTTP │  SQLite + SQLAlchemy      │HTTP │  simulator   │
└──────────────┘     └──────────────────────────┘     └──────────────┘
        ^                       │                              │
        │                       ▼                              ▼
   YES/NO taps        deterministic parser            demo trade only
                      idempotent commands             + management events
```

- **Telegram bot** (`telegram_bot/`): thin client. Registers testers, sends
  trade cards with YES/NO buttons, relays decisions to the backend. No trading
  logic lives here.
- **Backend** (`backend/`): the source of truth. Parses signals
  deterministically, enforces every safety rule (idempotency, expiry, admin
  pause, one-command-per-approval), exposes EA endpoints, records the full
  ledger and audit log.
- **MT5 EA** (`mt5_ea/SignalGateEA.mq5`): polls the backend, validates, places
  **demo** trades, manages TP stages and SL movement, reports every event.
- **Simulator** (`simulator/`): a Python stand-in for the EA so the whole flow
  can be tested without MetaTrader. Places no trades.

## End-to-end flow

1. Admin issues `/testsignal ...` (or `POST /signals/create`).
2. Backend **parses deterministically**. Valid → stored `VALID` with expiry;
   invalid → stored `REJECTED` with a reason. A performance ledger row is
   created either way.
3. Bot sends a structured **trade card** with YES/NO to testers.
4. User taps **YES** → `POST /signals/{id}/approve`. Backend runs all safety
   checks and creates **exactly one** command. **NO** → `reject`, no command.
5. EA/simulator polls `GET /commands/pending`. The oldest non-expired pending
   command is returned and atomically marked `SENT_TO_EA` (never handed out
   twice).
6. EA acks `POST /commands/{id}/received`, executes the demo trade, and reports
   `POST /commands/{id}/execution`.
7. As TP levels are hit and SLs move, the EA reports
   `POST /commands/{id}/management_event` for each transition.
8. Backend updates command status, performance ledger, and notifies the
   user/admin over Telegram.

## Data model (SQLite)

`users`, `signals`, `approvals` (unique on `signal_id+user_id`), `commands`,
`executions`, `trade_management_events`, `performance_ledger`, `audit_logs`,
`settings`. See `backend/app/models.py`.

## Auth (local prototype)

- EA endpoints: `X-EA-API-Key` header must equal `EA_API_KEY`.
- Admin endpoints: `X-Admin-Id` header must be in `ADMIN_TELEGRAM_IDS`.

This is intentionally lightweight — adequate for a local demo, **not**
production authentication.

## Why this shape

- **Human-in-the-loop**: every trade is explicitly approved. No auto-copy.
- **Deterministic boundary**: a single parser converts text → structure. If it
  can't be certain, it rejects. Nothing ambiguous reaches the broker.
- **Idempotent backend**: duplicate taps, expired signals and paused state are
  handled centrally so the EA stays simple.
