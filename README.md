# SignalGate

**Telegram-to-MetaTrader 5 one-tap DEMO trade execution system.**

SignalGate turns an admin's structured trade signal into a Telegram **trade
card**. A registered tester taps **YES** or **NO**. On YES, the backend creates
exactly one validated command, a MetaTrader 5 Expert Advisor (or a Python
simulator) places a **demo** trade, manages take-profit stages and stop-loss
movement, and reports every event back. Everything is logged and recorded in a
performance ledger.

> ⚠️ **DEMO ONLY.** v1 has no live-account support, by design. No money is at
> risk. No profitability is claimed anywhere.

## What this is

- A human-in-the-loop signal **approval** and **execution-tracking** system.
- A deterministic boundary between free Telegram text and the trading terminal.
- A forward-testing harness with a full audit trail and performance ledger.

## What works in v1

- Deterministic signal parser (XAUUSD / GOLD / XAU; BUY/SELL; SL + TP1–TP3).
- FastAPI backend (SQLite) with idempotent approvals and commands.
- Telegram bot: `/start`, `/status`, `/settings`, and admin `/testsignal`,
  `/pause`, `/resume`, `/users`, `/lastsignals`, `/lastcommands`.
- Inline YES/NO trade cards with precise outcome messages.
- MT5 Expert Advisor (`SignalGateEA.mq5`): polls, validates, places demo
  trades, split-ticket partial profits, SL staging, full event reporting.
- Python EA **simulator** to run the whole flow without MetaTrader.
- Performance ledger + audit logs across the full lifecycle.
- Pytest suite (parser, approvals, commands, expiry, admin pause, ledger,
  end-to-end simulator).

## What does NOT exist in v1 (intentionally)

- ❌ Live trading / live accounts
- ❌ Full auto-copying (every trade needs an explicit YES)
- ❌ Trailing stops
- ❌ Payments, public landing page, customer dashboard
- ❌ AI that decides, validates, or approves trades. A vision model is used
  **only** to transcribe a signal *screenshot* into candidate text; that text
  goes through the same deterministic `parser.py` (the sole authority on
  validity), and a human provider must confirm every extraction before any card
  is sent. No trade number ever bypasses the deterministic parser.

## Why raw Telegram text never reaches MetaTrader

Free text is ambiguous and unsafe to trade on directly. SignalGate parses text
**once**, deterministically, into structured fields and **rejects** anything
uncertain (missing SL/TP, both directions, inconsistent SL vs TP, bad ordering,
non-numeric values). Only structured, validated, **approved** command JSON is
ever served to the EA. The EA has no idea the original Telegram text existed.

## Why split-ticket mode for partial profits

The spec wants 50/25/25 partial closes, but most symbols have a 0.01 minimum
lot **and** 0.01 lot step. You cannot partially close a single 0.01 lot
position by 50% (that needs 0.005 lots). So in demo we open **three child
positions** that emulate partials:

| Child | Lot | Take-profit | On close |
|-------|-----|-------------|----------|
| TP1 | 0.02 | TP1 | move remaining SLs to **breakeven** |
| TP2 | 0.01 | TP2 | move TP3 child SL to **TP1** |
| TP3 | 0.01 | TP3 | full close → `FULLY_CLOSED` |

Total demo exposure ≈ 0.04 lots, all sharing the same initial SL. This is
clearly named `split_ticket_demo_partial_mode` and is the v1 default. A
single-ticket fallback (one 0.01 lot, full close at the final TP) is also
supported. This is **demo only** and documented, not hidden.

## Quick start

Full instructions: [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

```bash
# 0. Configure
cp .env.example .env   # set TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS, EA_API_KEY

# 1. Backend (Terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python ../scripts/init_db.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 2. Telegram bot (Terminal 2)
cd telegram_bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_bot.py

# 3. EA simulator (Terminal 3 — no MetaTrader needed)
python simulator/ea_simulator.py --user-id USER-000001 --api-key local-demo-ea-key
```

One-command scripted demo (no Telegram):

```bash
python simulator/run_demo_flow.py --admin-id <YOUR_ADMIN_ID> --api-key local-demo-ea-key
```

## Install the MT5 EA

See [`mt5_ea/README_MT5_SETUP.md`](mt5_ea/README_MT5_SETUP.md). In short: copy
`SignalGateEA.mq5` into `MQL5/Experts`, compile (F7), whitelist the backend URL
under Tools → Options → Expert Advisors → WebRequest, enable Algo Trading, and
attach it to a **demo** XAUUSD chart with your `UserID` and `EAApiKey`.

## Run the tests

```bash
cd backend && source .venv/bin/activate && python -m pytest -q
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Local setup](docs/LOCAL_SETUP.md)
- [Demo script](docs/DEMO_SCRIPT.md)
- [Testing plan](docs/TESTING_PLAN.md)
- [Safety rules](docs/SAFETY_RULES.md)
- [Performance ledger](docs/PERFORMANCE_LEDGER.md)
- [Nick screenshot provider guide](docs/NICK_SCREENSHOT_PROVIDER_GUIDE.md)
- [Copy-paste message to Nick](docs/MESSAGE_TO_NICK.md)
- [Ben next-stage checklist](docs/BEN_NEXT_STAGE_CHECKLIST.md)
- [MT5 setup](mt5_ea/README_MT5_SETUP.md)

## Known limitations

- **Auth is lightweight** (shared API key + admin-id header) — fine for local
  use, not production.
- **MQL5 has no JSON library**; the EA uses a small deterministic extractor for
  the exact backend command shape (see MT5 README).
- **Demo/live detection** depends on the broker reporting `ACCOUNT_TRADE_MODE`
  correctly; keep `DemoOnlyMode = true` and only attach to demo accounts.
- **R values are approximate** and marked provisional when entry price is
  unknown. No profitability is claimed.
- The bot broadcasts each confirmed trade card to **every active registered
  tester** (via `GET /signals/recipients`), not just the issuing admin.

## Next steps after v1

- Persist per-user Telegram chat ids for true multi-tester broadcast.
- Stronger auth (per-EA keys, signed requests).
- Richer ledger reporting / export.
- Optional (carefully gated) trailing stop and additional symbols.
- Live trading would require a separate, deliberate, risk-reviewed design — out
  of scope here.

## Safety

This is a demo, risk-controlled, execution-tracking and forward-testing tool.
It is not financial advice and makes no profitability claims. See
[`docs/SAFETY_RULES.md`](docs/SAFETY_RULES.md).
