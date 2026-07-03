# Claude Code Master Build Prompt  
# SignalGate: Telegram-to-MetaTrader One-Tap Demo Trade Execution System

You are Claude Code acting as the lead full-stack engineer for this project.

Your job is to build a complete working local prototype of **SignalGate**, a Telegram-to-MetaTrader 5 demo trade execution system.

This is not a mockup. Build the real end-to-end system.

The required flow is:

Telegram test signal  
→ deterministic signal parser  
→ structured trade card sent to registered Telegram testers  
→ user taps YES or NO  
→ backend records approval/rejection  
→ backend creates one approved command if YES  
→ MT5 Expert Advisor polls backend  
→ EA validates command  
→ EA places demo trade only  
→ EA manages take-profit stages, partial profits, and stop-loss movement  
→ EA reports all execution and management events  
→ backend records full ledger  
→ Telegram bot confirms trade lifecycle events to user/admin

## Non-negotiable safety constraints

These are absolute.

1. Demo trading only.
2. No live account support in v1.
3. No full auto-copying in v1.
4. No raw Telegram text may ever reach MetaTrader.
5. MetaTrader receives only structured, validated, approved backend commands.
6. Every trade must open with an initial hard stop loss.
7. A YES approval creates exactly one command.
8. A NO rejection creates no command.
9. Duplicate YES clicks must not create duplicate commands.
10. Expired signals must not create commands.
11. Admin pause must block command creation.
12. EA must never execute the same command twice.
13. EA must report success or failure for every command.
14. Every partial close, stop-loss movement, failure, and state transition must be logged.
15. No trailing stop in v1.
16. No payment system.
17. No public landing page.
18. No customer dashboard beyond basic admin logs/endpoints.
19. No AI parsing in v1. Use deterministic parsing only.
20. Do not add extra product features unless explicitly required here.

## Important technical correction

The original product concept says “fixed 0.01 lot initially” and also requires 50/25/25 partial closes.

In real MT5/broker environments, many symbols have a minimum lot and lot step of 0.01. A single 0.01 lot position cannot be partially closed by 50%, 25%, 25%, because that would require closing 0.005 or 0.0025 lots.

Therefore implement this safely:

### EA trade-sizing rule for v1

Support two execution modes:

1. **Single-ticket fallback mode**
   - Opens one demo position.
   - Uses broker-compatible lot size.
   - Can close full position at TP1 or TP3 depending on settings.
   - Used only if split-ticket mode is disabled or impossible.

2. **Split-ticket partial-profit mode**, default for v1 demo testing
   - Instead of opening one 0.01 lot trade and trying impossible partial closes, open separate child positions representing TP portions.
   - For 50/25/25 management, open 3 child orders:
     - TP1 child: 0.02 lots
     - TP2 child: 0.01 lots
     - TP3 child: 0.01 lots
   - Total demo exposure: 0.04 lots.
   - All child positions use same entry direction and initial SL.
   - TP1 child closes at TP1, then EA moves remaining child SLs to breakeven.
   - TP2 child closes at TP2, then EA moves TP3 child SL to TP1.
   - TP3 child closes at TP3.
   - Each child ticket must be linked to the same command_id.
   - This is demo only and must be clearly named in code/settings as `split_ticket_demo_partial_mode`.

Default v1 settings:
- `demo_only_mode = true`
- `split_ticket_demo_partial_mode = true`
- `tp1_lot = 0.02`
- `tp2_lot = 0.01`
- `tp3_lot = 0.01`
- `single_ticket_fixed_lot = 0.01`

Do not hide this. Document it clearly in README.

## Project structure

Create a monorepo with this structure:

```text
signalgate/
  backend/
    app/
      __init__.py
      main.py
      config.py
      database.py
      models.py
      schemas.py
      crud.py
      parser.py
      security.py
      ledger.py
      telegram_service.py
      routes/
        __init__.py
        health.py
        users.py
        signals.py
        commands.py
        ea.py
        admin.py
    tests/
      test_parser.py
      test_approvals.py
      test_commands.py
      test_expiry.py
      test_admin_pause.py
      test_ledger.py
    requirements.txt
    run_backend.py

  telegram_bot/
    bot.py
    handlers.py
    keyboards.py
    config.py
    requirements.txt
    run_bot.py

  mt5_ea/
    SignalGateEA.mq5
    README_MT5_SETUP.md

  simulator/
    ea_simulator.py
    run_demo_flow.py

  docs/
    ARCHITECTURE.md
    LOCAL_SETUP.md
    DEMO_SCRIPT.md
    TESTING_PLAN.md
    SAFETY_RULES.md
    PERFORMANCE_LEDGER.md

  scripts/
    init_db.py
    seed_settings.py
    reset_local_db.py

  .env.example
  README.md
```

Use Python, FastAPI, SQLite, SQLAlchemy, Pydantic, pytest, and python-telegram-bot.

Use MT5/MQL5 for the EA.

Also build a Python EA simulator so the backend/Telegram flow can be tested without MetaTrader installed. This simulator must poll the backend like the EA and post execution/management events, but it must be clearly marked as simulator-only.

## Environment variables

Create `.env.example` with:

```env
DATABASE_URL=sqlite:///./signalgate.db
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
BACKEND_BASE_URL=http://127.0.0.1:8000

TELEGRAM_BOT_TOKEN=replace_me
ADMIN_TELEGRAM_IDS=123456789

EA_API_KEY=local-demo-ea-key
DEMO_ONLY_MODE=true
DEFAULT_SIGNAL_EXPIRY_MINUTES=5
DEFAULT_LOT_SIZE=0.01
SPLIT_TICKET_DEMO_PARTIAL_MODE=true
TP1_LOT=0.02
TP2_LOT=0.01
TP3_LOT=0.01
MAX_SPREAD_POINTS=500
MAX_SLIPPAGE_POINTS=100
```

Never commit real tokens.

## Database schema

Implement these SQLAlchemy models.

### users

Fields:
- id: string primary key, e.g. USER-000001
- telegram_user_id: string unique
- telegram_username: string nullable
- first_name: string nullable
- status: string, default ACTIVE
- risk_percent: float nullable
- fixed_lot_size: float default 0.01
- license_key: string nullable
- created_at: datetime
- updated_at: datetime

### signals

Fields:
- id: string primary key, e.g. SIG-000001
- source: string, default TELEGRAM_ADMIN_TEST
- source_message_id: string nullable
- raw_text: text
- symbol: string nullable
- direction: string nullable, BUY/SELL
- entry_type: string nullable, MARKET/LIMIT
- entry_price: float nullable
- initial_stop_loss: float nullable
- tp1: float nullable
- tp2: float nullable
- tp3: float nullable
- parser_status: string, VALID/REJECTED
- parser_error: text nullable
- created_at: datetime
- expires_at: datetime
- status: string, NEW/VALID/REJECTED/EXPIRED/CANCELLED
- edited_marker: bool default false
- deleted_marker: bool default false

### approvals

Fields:
- id: string primary key, e.g. APP-000001
- signal_id: foreign key
- user_id: foreign key
- decision: YES/NO
- created_at: datetime
- status: APPROVED/REJECTED/DUPLICATE/EXPIRED/BLOCKED

Add unique constraint on `(signal_id, user_id)`.

### commands

Fields:
- id: string primary key, e.g. CMD-000001
- signal_id: foreign key
- approval_id: foreign key
- user_id: foreign key
- symbol
- direction
- entry_type
- entry_price nullable
- initial_stop_loss
- tp1
- tp2 nullable
- tp3 nullable
- tp1_close_percent default 50
- tp2_close_percent default 25
- tp3_close_percent default 25
- lot_size default 0.01
- split_ticket_demo_partial_mode bool default true
- tp1_lot nullable
- tp2_lot nullable
- tp3_lot nullable
- risk_percent nullable
- status:
  - PENDING
  - SENT_TO_EA
  - EXECUTED_OPEN
  - PARTIAL_TP1_DONE
  - PARTIAL_TP2_DONE
  - FULLY_CLOSED
  - REJECTED
  - EXPIRED
  - FAILED
  - CANCELLED
- created_at
- expires_at
- sent_to_ea_at nullable
- processed_at nullable
- last_error nullable

### executions

Fields:
- id: string primary key, e.g. EXE-000001
- command_id: foreign key
- user_id: foreign key
- status: SUCCESS/FAILED
- broker_ticket: string nullable
- child_tickets_json: text nullable
- executed_symbol
- executed_direction
- requested_price nullable
- executed_price nullable
- lot_size
- initial_stop_loss
- tp1 nullable
- tp2 nullable
- tp3 nullable
- spread_at_execution nullable
- slippage nullable
- error_code nullable
- error_message nullable
- created_at

### trade_management_events

Fields:
- id: string primary key, e.g. MGT-000001
- command_id: foreign key
- broker_ticket nullable
- event_type:
  - OPENED
  - TP1_REACHED
  - TP1_CLOSE_REQUESTED
  - TP1_CLOSE_SUCCESS
  - TP1_CLOSE_FAILED
  - SL_MOVE_BREAKEVEN_REQUESTED
  - SL_MOVE_BREAKEVEN_SUCCESS
  - SL_MOVE_BREAKEVEN_FAILED
  - TP2_REACHED
  - TP2_CLOSE_REQUESTED
  - TP2_CLOSE_SUCCESS
  - TP2_CLOSE_FAILED
  - SL_MOVE_TP1_REQUESTED
  - SL_MOVE_TP1_SUCCESS
  - SL_MOVE_TP1_FAILED
  - TP3_REACHED
  - TP3_CLOSE_SUCCESS
  - TP3_CLOSE_FAILED
  - FULLY_CLOSED
  - STOP_LOSS_HIT
  - FAILED_MANAGEMENT
- stage: OPENED/TP1_DONE/TP2_DONE/TP3_DONE/FULLY_CLOSED/FAILED_MANAGEMENT
- requested_action nullable
- result: SUCCESS/FAILED/PENDING
- price nullable
- lot_size_before nullable
- lot_size_after nullable
- stop_loss_before nullable
- stop_loss_after nullable
- error_code nullable
- error_message nullable
- created_at

### performance_ledger

Fields:
- id
- signal_id
- command_id nullable
- symbol
- direction
- entry_price nullable
- initial_stop_loss
- tp1 nullable
- tp2 nullable
- tp3 nullable
- result_status:
  - PENDING
  - APPROVED_NOT_EXECUTED
  - EXECUTED_OPEN
  - TP1_HIT
  - TP2_HIT
  - TP3_HIT
  - STOPPED_OUT
  - BREAKEVEN
  - FAILED
  - REJECTED
  - EXPIRED
- r_result nullable
- max_favourable_excursion nullable
- max_adverse_excursion nullable
- signal_to_card_delay nullable
- approval_to_execution_delay nullable
- slippage nullable
- spread_at_execution nullable
- final_notes nullable
- created_at
- updated_at

### audit_logs

Fields:
- id
- event_type
- entity_type
- entity_id
- payload_json
- created_at

### settings

Fields:
- id
- key unique
- value
- updated_at

Seed settings:
- admin_paused=false
- default_signal_expiry_minutes=5
- max_spread=500
- max_slippage=100
- demo_only_mode=true
- default_lot_size=0.01
- split_ticket_demo_partial_mode=true
- tp1_lot=0.02
- tp2_lot=0.01
- tp3_lot=0.01
- tp1_close_percent=50
- tp2_close_percent=25
- tp3_close_percent=25

## Backend API

Build FastAPI app.

### General requirements

- Use Pydantic schemas for request/response bodies.
- Use clear error responses.
- Log all important events to `audit_logs`.
- Enforce idempotency.
- Never allow duplicate command creation for same signal/user approval.
- Expire old signals/commands.
- Use UTC timestamps.
- Add simple API-key auth for EA endpoints using `X-EA-API-Key`.
- Add admin auth for admin endpoints using simple `X-Admin-Id` header matching env admin ids.
- For local prototype this is enough.

### Endpoints

#### GET /health

Return:

```json
{
  "status": "ok",
  "demo_only_mode": true,
  "admin_paused": false
}
```

#### POST /register_user

Request:
```json
{
  "telegram_user_id": "123",
  "telegram_username": "ben",
  "first_name": "Ben"
}
```

Creates or updates a user.

#### POST /signals/create

Admin only.

Request:
```json
{
  "raw_text": "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363",
  "source": "TELEGRAM_ADMIN_TEST",
  "source_message_id": "optional"
}
```

Actions:
- Store raw signal.
- Parse deterministically.
- If valid, set status VALID and expiry.
- If rejected, store parser error.
- Create performance ledger row for every signal.
- Return structured signal.

#### GET /signals/recent

Admin only.

Return recent signals.

#### POST /signals/{signal_id}/approve

Request:
```json
{
  "telegram_user_id": "123"
}
```

Actions:
- Check user exists and active.
- Check admin pause false.
- Check signal exists.
- Check signal valid.
- Check not expired.
- Check approval does not already exist.
- Create approval with YES.
- Create exactly one command.
- Use default lot settings.
- Return command.

Duplicate approval should return existing approval/command and message saying duplicate blocked.

#### POST /signals/{signal_id}/reject

Request:
```json
{
  "telegram_user_id": "123"
}
```

Actions:
- Create rejection approval if none exists.
- Create no command.
- Duplicate rejection should be idempotent.

#### GET /commands/pending

EA only.

Query params:
- user_id
- license_key optional

Actions:
- Return the oldest pending non-expired command for user.
- Mark it SENT_TO_EA.
- Set sent_to_ea_at.
- Never return expired commands.
- Never return already sent/processed commands unless explicitly reset by admin.

Response example:

```json
{
  "command_id": "CMD-000001",
  "signal_id": "SIG-000001",
  "approval_id": "APP-000001",
  "user_id": "USER-000001",
  "symbol": "XAUUSD",
  "direction": "BUY",
  "entry_type": "MARKET",
  "entry_price": null,
  "initial_stop_loss": 2343.0,
  "take_profits": [
    {
      "level": 1,
      "price": 2353.0,
      "close_percent": 50,
      "lot": 0.02,
      "move_sl_to": "BREAKEVEN"
    },
    {
      "level": 2,
      "price": 2358.0,
      "close_percent": 25,
      "lot": 0.01,
      "move_sl_to": "TP1"
    },
    {
      "level": 3,
      "price": 2363.0,
      "close_percent": 25,
      "lot": 0.01,
      "move_sl_to": null
    }
  ],
  "lot_size": 0.01,
  "split_ticket_demo_partial_mode": true,
  "expires_at": "2026-06-01T18:00:00Z",
  "demo_only": true
}
```

If no command:
```json
{
  "command": null
}
```

#### POST /commands/{command_id}/received

EA only.

Marks EA received command. Log audit event.

#### POST /commands/{command_id}/execution

EA only.

Request includes:
- status
- broker_ticket
- child_tickets_json
- executed_symbol
- executed_direction
- requested_price
- executed_price
- lot_size
- initial_stop_loss
- tp1
- tp2
- tp3
- spread_at_execution
- slippage
- error_code
- error_message

Actions:
- Create execution row.
- If success, command status EXECUTED_OPEN.
- If failed, command status FAILED.
- Update performance ledger.
- Send Telegram confirmation to user/admin if bot token configured.

#### POST /commands/{command_id}/management_event

EA only.

Request includes:
- broker_ticket
- event_type
- stage
- requested_action
- result
- price
- lot_size_before
- lot_size_after
- stop_loss_before
- stop_loss_after
- error_code
- error_message

Actions:
- Store management event.
- Update command status according to event.
- Update performance ledger.
- Send Telegram confirmation for major events.

#### POST /admin/pause

Admin only. Sets admin_paused=true.

#### POST /admin/resume

Admin only. Sets admin_paused=false.

#### GET /admin/status

Admin only. Returns settings and counts.

#### GET /ea/heartbeat

EA only. Records heartbeat audit log and returns status.

## Deterministic signal parser

Create `backend/app/parser.py`.

Support these formats:

```text
XAUUSD BUY
Entry: Market
SL: 2343
TP1: 2353
TP2: 2358
TP3: 2363
```

And:

```text
GOLD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363
```

Alias mapping:
- GOLD → XAUUSD
- XAU → XAUUSD
- XAUUSD → XAUUSD
- BUY/LONG → BUY
- SELL/SHORT → SELL
- SL/STOP/STOPLOSS/STOP LOSS → stop loss
- TP/TP1/TAKEPROFIT/TAKE PROFIT → take profit

Parser output:
- raw_text
- symbol
- direction
- entry_type
- entry_price
- initial_stop_loss
- tp1
- tp2
- tp3
- parser_status
- parser_error
- expires_at

Reject if:
- no symbol
- no direction
- both BUY and SELL appear
- no stop loss
- no TP1
- invalid numeric values
- stop loss invalid for direction
  - BUY: SL must be below TP levels
  - SELL: SL must be above TP levels
- impossible TP ordering
  - BUY: TP1 < TP2 < TP3 where present
  - SELL: TP1 > TP2 > TP3 where present
- parser confidence insufficient

Implement parser tests.

Required parser tests:
1. `XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363` valid.
2. `GOLD BUY SL 2343 TP1 2353 TP2 2358` valid.
3. `XAU SELL SL 2355 TP1 2345 TP2 2340` valid.
4. `BUY XAUUSD TP1 2353` rejected missing SL.
5. Random text rejected.
6. Text with both BUY and SELL rejected.
7. BUY with SL above TP rejected.
8. SELL with SL below TP rejected.
9. BUY with TP2 lower than TP1 rejected.
10. SELL with TP2 higher than TP1 rejected.

## Telegram bot

Build `telegram_bot`.

Use `python-telegram-bot`.

Commands:

### /start

Registers tester with backend.

Reply:
```text
SignalGate demo tester registered.
Demo mode only. No live trades.
```

### /status

Shows:
- registered/not registered
- active/inactive
- backend health
- admin paused true/false

### /settings

Shows:
- demo only
- expiry minutes
- split ticket partial mode
- lot settings

### /testsignal

Admin only.

Example:
```text
/testsignal XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363
```

Actions:
- Call backend `/signals/create`.
- If rejected, show parser error.
- If valid, send structured trade card to all active users.
- For v1, it is okay to send to the admin and registered local testers.

### /pause

Admin only. Calls backend pause.

### /resume

Admin only. Calls backend resume.

### /users

Admin only. Shows active users.

### /lastsignals

Admin only. Shows recent signals.

### /lastcommands

Admin only. Shows recent commands.

## Telegram trade card

Send with inline YES/NO buttons.

Example:

```text
New Demo Signal

XAUUSD BUY
Entry: Market
Initial SL: 2343.00

TP1: 2353.00
Close TP1 child / move remaining SL to breakeven

TP2: 2358.00
Close TP2 child / move remaining SL to TP1

TP3: 2363.00
Close final child

Demo mode only.
Split-ticket partial mode: ON
Expires in: 5 minutes

Approve this demo trade?
```

Buttons:
- YES: Place Demo Trade
- NO: Ignore

Callback logic:
- YES calls backend approve endpoint.
- NO calls backend reject endpoint.
- Show precise result:
  - Approved. Waiting for MetaTrader EA to execute demo trade.
  - Rejected. No trade command created.
  - Already approved. No duplicate command created.
  - Signal expired. No command created.
  - Trading paused. No command created.
  - Parser rejected signal. No command created.

## MT5 EA requirements

Create `mt5_ea/SignalGateEA.mq5`.

The EA must be a genuine MQL5 Expert Advisor skeleton capable of polling FastAPI using WebRequest.

Inputs:
```mql5
input string BackendURL = "http://127.0.0.1:8000";
input string UserID = "USER-000001";
input string LicenseKey = "local-demo";
input string EAApiKey = "local-demo-ea-key";
input int PollIntervalSeconds = 2;
input double SingleTicketFixedLot = 0.01;
input bool SplitTicketDemoPartialMode = true;
input double TP1Lot = 0.02;
input double TP2Lot = 0.01;
input double TP3Lot = 0.01;
input long MagicNumber = 440044;
input bool DemoOnlyMode = true;
input int MaxSpreadPoints = 500;
input int MaxSlippagePoints = 100;
input bool EnableTrading = true;
input string SymbolOverride = "";
```

### EA behaviour

OnInit:
- Validate DemoOnlyMode is true.
- Set timer to PollIntervalSeconds.
- Print setup instructions if WebRequest not allowed.
- Send heartbeat.

OnTimer:
- If trading disabled, do nothing.
- Poll `/commands/pending`.
- If no command, do nothing.
- If command returned:
  - Check command_id not already processed locally.
  - Validate demo_only true.
  - Validate symbol exists.
  - Validate spread under max.
  - Validate SL/TP logic.
  - Validate command not expired.
  - Call `/commands/{id}/received`.
  - Execute trade in demo.

### Demo account guard

MQL5 may not reliably expose broker account demo/live in all environments, but try:
- Check account trade mode if available.
- If account appears live and DemoOnlyMode true, refuse to trade and report DEMO_ONLY_VIOLATION.
- Always keep DemoOnlyMode default true.

### Execution

For `SplitTicketDemoPartialMode=true`:
- Open TP1 child position with TP1Lot.
- Open TP2 child position with TP2Lot.
- Open TP3 child position with TP3Lot.
- All with same initial SL.
- Set TP on each child where possible:
  - TP1 child TP = TP1
  - TP2 child TP = TP2
  - TP3 child TP = TP3
- Store child tickets linked to command_id.
- Report execution with child_tickets_json.

Management:
- Monitor child positions.
- When TP1 child closes/hits TP1:
  - Report TP1_CLOSE_SUCCESS.
  - Move SL on remaining child positions to breakeven/open price.
  - Report SL_MOVE_BREAKEVEN_SUCCESS or failure.
- When TP2 child closes/hits TP2:
  - Report TP2_CLOSE_SUCCESS.
  - Move SL on TP3 child to TP1.
  - Report SL_MOVE_TP1_SUCCESS or failure.
- When TP3 child closes:
  - Report TP3_CLOSE_SUCCESS.
  - Report FULLY_CLOSED.
- If SL hit on remaining tickets, report STOP_LOSS_HIT.

For single-ticket fallback:
- Open one 0.01 lot position with SL and final TP.
- Report events.
- Do not attempt impossible partial closes below lot step.

### EA idempotency

The EA must maintain a local in-memory set/list of processed command IDs while running.

If same command appears again:
- Do not trade.
- Report DUPLICATE_COMMAND.

### EA error reporting

Report these errors:
- COMMAND_EXPIRED
- SYMBOL_NOT_FOUND
- SPREAD_TOO_HIGH
- PRICE_MOVED_TOO_FAR
- INVALID_STOP_LOSS
- INVALID_TAKE_PROFIT
- LOT_SIZE_INVALID
- MARGIN_INSUFFICIENT
- TRADING_DISABLED
- ORDER_SEND_FAILED
- DUPLICATE_COMMAND
- DEMO_ONLY_VIOLATION
- WEBREQUEST_FAILED
- JSON_PARSE_FAILED

### MQL5 JSON

Keep it simple and robust.

Either:
- include a self-contained minimal JSON parser inside the EA file, or
- implement deterministic extraction for the exact backend command JSON shape.

Do not rely on unbundled external MQL5 libraries.

Document any limitation.

## Python EA simulator

Build `simulator/ea_simulator.py`.

Purpose:
- Allows full backend and Telegram flow testing without MT5.
- Polls `/commands/pending`.
- Marks command received.
- Posts fake execution success.
- Posts fake TP1, SL move, TP2, SL move, TP3, FULLY_CLOSED events.
- Uses delays or immediate mode.
- Clearly prints that it is simulator only and not trading.

CLI:
```bash
python simulator/ea_simulator.py --user-id USER-000001 --api-key local-demo-ea-key --backend http://127.0.0.1:8000
```

## Performance ledger

Implement `backend/app/ledger.py`.

Ledger must update on:
- signal creation
- approval
- rejection
- command creation
- execution success/failure
- TP1 event
- TP2 event
- TP3 event
- stop loss hit
- full close
- failure

For v1, R calculation can be approximate:
- BUY:
  - risk = entry_price - initial_stop_loss
  - reward to TP = tp_price - entry_price
- SELL:
  - risk = initial_stop_loss - entry_price
  - reward to TP = entry_price - tp_price

If executed_price missing, use entry/market placeholder and set final_notes saying R is provisional.

Do not fake profitability. Be conservative.

## Tests

Use pytest.

Minimum tests:

### Parser tests
As listed above.

### Approval tests
- YES creates one command.
- Duplicate YES does not create second command.
- NO creates no command.
- NO after YES does not cancel existing command unless explicitly designed; for v1, reject after approve should be blocked.
- YES after NO should be blocked unless admin resets; for v1, first decision wins.

### Expiry tests
- Expired signal cannot be approved.
- Expired command not returned to EA.

### Admin pause tests
- Admin pause blocks command creation.
- Resume restores approvals.

### Command tests
- Pending command returned once.
- SENT_TO_EA command not returned again.
- Failed command recorded.
- Execution success updates status.
- Management events update status.

### Ledger tests
- Signal creates ledger row.
- Rejection updates ledger.
- Execution updates ledger.
- TP1/TP2/TP3 events update ledger.

### Simulator test
- Create signal.
- Approve.
- Simulator polls.
- Execution and management events recorded.
- Command ends FULLY_CLOSED.

## Local setup

Create clear run instructions.

Expected local flow:

Terminal 1:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python ../scripts/init_db.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:
```bash
cd telegram_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_bot.py
```

Terminal 3 simulator:
```bash
python simulator/ea_simulator.py --user-id USER-000001 --api-key local-demo-ea-key
```

MT5:
- Copy `SignalGateEA.mq5` into MQL5/Experts.
- Compile in MetaEditor.
- Enable Algo Trading.
- Add backend URL to WebRequest allowed URLs.
- Attach EA to XAUUSD chart.
- Use demo account only.

## Demo script

Create `docs/DEMO_SCRIPT.md`.

Steps:
1. Start backend.
2. Start Telegram bot.
3. Register user with `/start`.
4. Admin sends:
   `/testsignal XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363`
5. User receives trade card.
6. User presses YES.
7. Backend creates command.
8. Simulator or EA receives command.
9. Execution is reported.
10. TP1 event is reported.
11. SL move to breakeven is reported.
12. TP2 event is reported.
13. SL move to TP1 is reported.
14. TP3 event is reported.
15. FULLY_CLOSED is reported.
16. Admin checks logs and ledger.

## README requirements

The root README must explain:

- What SignalGate is.
- Demo-only status.
- What works in v1.
- What does not exist in v1.
- Why raw Telegram text never reaches MT5.
- Why split-ticket mode is used for partial profits.
- How to run backend.
- How to run Telegram bot.
- How to run simulator.
- How to install MT5 EA.
- How to run tests.
- Known limitations.
- Next steps after v1.

## Build order

Work in this order:

1. Create repo structure.
2. Add backend requirements.
3. Build config/database/models.
4. Build parser and parser tests.
5. Build backend endpoints.
6. Build approval/command idempotency.
7. Build ledger updates.
8. Build Telegram bot.
9. Build EA simulator.
10. Build MT5 EA file.
11. Build docs.
12. Run tests.
13. Fix failures.
14. Provide final summary with:
    - files created
    - what works
    - how to run it
    - what still needs manual setup
    - MT5 limitations
    - any known risks

## Coding standards

- Keep code readable.
- Use type hints in Python.
- Use Pydantic models.
- Keep route logic thin; move core logic into crud/services.
- Add comments around safety-critical logic.
- Do not over-engineer.
- Prefer working local prototype over enterprise abstractions.
- Do not introduce Docker unless everything else is working.
- Do not add Celery, Redis, Stripe, React, dashboards, OAuth, or other extras.
- Do not use AI signal parsing.
- Do not make profitability claims anywhere in the app or docs.
- Use honest language: “demo”, “forward testing”, “ledger”, “risk-controlled”, “execution tracking”.

## Acceptance criteria

The build is complete when:

1. Backend starts locally.
2. Database initializes.
3. Parser accepts valid XAUUSD/GOLD signals.
4. Parser rejects unsafe/ambiguous signals.
5. Telegram `/start` registers user.
6. Admin `/testsignal` creates parsed signal.
7. User receives trade card.
8. YES creates one command.
9. NO creates no command.
10. Duplicate YES blocked.
11. Expired signal blocked.
12. Admin pause blocks command creation.
13. Simulator can poll command.
14. Simulator can report execution and all management events.
15. Backend records execution.
16. Backend records TP1/TP2/TP3/SL movement events.
17. Performance ledger updates.
18. MT5 EA file exists and implements polling/execution/management logic as far as possible in MQL5.
19. README and setup docs are clear.
20. Test suite passes.

## Final instruction

Begin building now.

Do not ask product questions unless truly blocked.

Make reasonable local-prototype decisions.

Keep all v1 behaviour demo-only, transparent, idempotent, and heavily logged.

The first milestone is not a pretty UI. The first milestone is this:

A Telegram tester receives a structured demo trade card, taps YES, the backend creates one safe command, the EA or simulator receives it, demo execution is reported, TP/SL management events are logged, and the performance ledger shows the full lifecycle.
