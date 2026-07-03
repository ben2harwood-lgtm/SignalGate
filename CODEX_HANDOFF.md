# SignalGate Codex Handoff

Date: 2026-06-30
Workspace: `/Users/benharwood/Desktop/signalgate`
Branch: `feat/signalgate-prototype`

This file is the copy/paste handoff for the next Codex agent. It summarizes the
current repo state, build intent, safety rules, runbook, tests, commits, and
continuation notes. The authoritative full build spec is still in `AGENTS.md`.

## Mission

SignalGate is a Telegram-to-MetaTrader 5 demo-only trade execution prototype.
The v1 flow is:

1. Admin or signal provider submits a test signal.
2. Backend parses it deterministically.
3. Telegram bot sends a structured demo trade card to registered testers.
4. Tester taps YES or NO.
5. YES creates exactly one validated command.
6. NO creates no command.
7. MT5 EA or Python simulator polls backend for approved commands.
8. EA/simulator reports execution and management events.
9. Backend records execution, trade-management events, audit logs, and ledger.
10. Telegram bot confirms lifecycle events where configured.

Keep the system demo-only, human-approved, idempotent, and heavily logged.

## Non-Negotiable Safety Invariants

- Demo trading only. No live account support in v1.
- No full auto-copying. Every command requires an explicit tester YES.
- Raw Telegram text never reaches MetaTrader.
- MT5 receives only structured, validated, approved backend command JSON.
- Every trade must open with an initial hard stop loss.
- A YES approval creates exactly one command.
- Duplicate YES clicks must not create duplicate commands.
- NO creates no command.
- First decision wins: NO after YES and YES after NO are blocked/idempotent.
- Expired signals cannot create commands.
- Expired commands are not returned to the EA.
- Admin pause blocks command creation.
- EA must not execute the same command twice.
- EA/simulator reports success or failure for every command.
- Every partial close, stop-loss movement, failure, and state transition is logged.
- No trailing stop, payments, public landing page, or customer dashboard in v1.
- No AI/fuzzy trade parsing in v1. Screenshot extraction may read candidate text,
  but the deterministic parser and a human confirmation still gate every signal.

## Current State

The core local prototype exists and is working:

- FastAPI backend with SQLite, SQLAlchemy models, Pydantic schemas, route modules,
  audit logs, settings, ledger, idempotent approvals, and EA API key auth.
- Deterministic parser for XAUUSD/GOLD/XAU BUY/SELL signals with SL/TP validation.
- Telegram bot with tester commands, admin commands, YES/NO callbacks, and trade
  card formatting.
- Screenshot-provider workflow:
  - `/provider CODE` can locally enroll a provider.
  - Provider can send image screenshots.
  - Backend `/signals/extract` reads candidate text using fake or Claude extractor.
  - Bot previews extraction with Confirm/Edit/Cancel.
  - Confirm calls the normal deterministic `/signals/create` path.
- Python EA simulator for full backend lifecycle without MT5.
- MT5 EA file exists at `mt5_ea/SignalGateEA.mq5` with WebRequest polling,
  validation, split-ticket demo partial mode, local duplicate guard, and event
  reporting.
- Hosted/multi-customer planning has been added:
  - `REQUIRE_LICENSE`
  - license issuance/activation/deactivation endpoints
  - hosted deployment docs
  - site mockups
  These additions must not weaken demo-only v1 behavior.

## Recent Verification

Test command run from repo root:

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

Result after the latest fix:

```text
50 passed, 4 warnings in 2.81s
```

Warnings are current technical debt, not failing behavior:

- Pydantic class-based config deprecation.
- FastAPI `on_event` lifespan deprecation.

Important test fix made during handoff:

- `backend/tests/conftest.py` now sets `SIGNAL_EXTRACTOR=fake`, so screenshot
  extraction tests stay offline and deterministic even when a local `.env` has
  a real `ANTHROPIC_API_KEY` or `SIGNAL_EXTRACTOR=claude`.

## Git State And Commits

Current branch:

```text
feat/signalgate-prototype
```

Commit history before this handoff file/test-env fix:

```text
ca1f4bd Extend screenshot extractor to read chart-zone signals
3a4491a Add Claude Code launch configs and ignore local settings
1d407cb Add SignalGate prototype implementation
4209b20 Add Claude build instructions
```

At the time this handoff was written, new local edits are:

```text
CODEX_HANDOFF.md
backend/tests/conftest.py
```

If the user wants everything captured as commits, stage and commit these two
files with a message like:

```bash
git add CODEX_HANDOFF.md backend/tests/conftest.py
git commit -m "Add Codex handoff and deterministic extractor tests"
```

## Files To Share

Use git-tracked files as the source of truth. Do not share ignored secrets,
virtualenvs, local DB files, or generated caches.

Tracked files currently include:

```text
.claude/launch.json
.env.example
.gitignore
AGENTS.md
CLAUDE.md
HOSTED_VERSION_PLAN.md
INSTALL_AND_USER_GUIDE.md
READ ME FIRST.txt
README.md
Start Backend.bat
Start Backend.command
Start Bot.bat
Start Bot.command
backend/app/__init__.py
backend/app/config.py
backend/app/crud.py
backend/app/database.py
backend/app/ledger.py
backend/app/main.py
backend/app/models.py
backend/app/parser.py
backend/app/routes/__init__.py
backend/app/routes/admin.py
backend/app/routes/commands.py
backend/app/routes/ea.py
backend/app/routes/health.py
backend/app/routes/signals.py
backend/app/routes/users.py
backend/app/schemas.py
backend/app/security.py
backend/app/telegram_service.py
backend/app/vision_extractor.py
backend/pytest.ini
backend/requirements-hosted.txt
backend/requirements.txt
backend/run_backend.py
backend/tests/__init__.py
backend/tests/conftest.py
backend/tests/test_admin_pause.py
backend/tests/test_approvals.py
backend/tests/test_commands.py
backend/tests/test_expiry.py
backend/tests/test_extract.py
backend/tests/test_ledger.py
backend/tests/test_licensing.py
backend/tests/test_parser.py
backend/tests/test_simulator.py
docs/ARCHITECTURE.md
docs/BEN_NEXT_STAGE_CHECKLIST.md
docs/DEMO_SCRIPT.md
docs/HOSTED_DEPLOYMENT.md
docs/LOCAL_SETUP.md
docs/MESSAGE_TO_NICK.md
docs/NICK_SCREENSHOT_PROVIDER_GUIDE.md
docs/PERFORMANCE_LEDGER.md
docs/SAFETY_RULES.md
docs/TESTING_PLAN.md
docs/WINDOWS_VPS_SETUP.md
mt5_ea/README_MT5_SETUP.md
mt5_ea/SignalGateEA.mq5
scripts/init_db.py
scripts/reset_local_db.py
scripts/seed_settings.py
simulator/ea_simulator.py
simulator/run_demo_flow.py
site-mockups/MESSAGE_MAP.md
site-mockups/_copy-deck.md
site-mockups/direction-1-quant-desk.html
site-mockups/direction-2-editorial-transparency.html
site-mockups/direction-3-verified-accountable.html
site-mockups/site-1-quant-desk.html
site-mockups/site-2-editorial-transparency.html
site-mockups/site-3-verified-accountable.html
telegram_bot/bot.py
telegram_bot/config.py
telegram_bot/handlers.py
telegram_bot/keyboards.py
telegram_bot/requirements.txt
telegram_bot/run_bot.py
```

Ignored/local files currently present and should not be committed or shared
unless intentionally exporting a local artifact:

```text
.DS_Store
.claude/settings.local.json
.env
SignalGate_share.zip
backend/.pytest_cache/
backend/.venv/
backend/signalgate.db
telegram_bot/.venv/
```

Never print or commit real Telegram, Anthropic, EA, or license secrets from
`.env`.

## Environment

Start from `.env.example`.

Required local values:

```env
DATABASE_URL=sqlite:///./signalgate.db
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
BACKEND_BASE_URL=http://127.0.0.1:8000

TELEGRAM_BOT_TOKEN=replace_me
ADMIN_TELEGRAM_IDS=123456789
SIGNAL_PROVIDER_TELEGRAM_IDS=
SIGNAL_PROVIDER_INVITE_CODE=

EA_API_KEY=local-demo-ea-key
REQUIRE_LICENSE=false
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

Screenshot extraction:

```env
SIGNAL_EXTRACTOR=fake
ANTHROPIC_API_KEY=replace_me
```

Use `fake` for offline plumbing. Use `claude` only when a real Anthropic key is
configured and the provider understands that the bot will still show a preview
and require Confirm/Edit/Cancel before broadcasting.

Settings are cached at process startup in several modules. Restart backend and
bot after changing `.env`.

## Local Runbook

Backend:

```bash
cd /Users/benharwood/Desktop/signalgate/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python ../scripts/init_db.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Telegram bot:

```bash
cd /Users/benharwood/Desktop/signalgate/telegram_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_bot.py
```

Simulator:

```bash
cd /Users/benharwood/Desktop/signalgate
python simulator/ea_simulator.py --user-id USER-000001 --api-key local-demo-ea-key --backend http://127.0.0.1:8000
```

Scripted no-Telegram demo:

```bash
cd /Users/benharwood/Desktop/signalgate
python simulator/run_demo_flow.py --admin-id YOUR_ADMIN_TELEGRAM_ID --api-key local-demo-ea-key
```

Tests:

```bash
cd /Users/benharwood/Desktop/signalgate/backend
source .venv/bin/activate
python -m pytest -q
```

Reset local DB:

```bash
cd /Users/benharwood/Desktop/signalgate
python scripts/reset_local_db.py
python scripts/init_db.py
```

## Manual Telegram Demo

1. Start backend.
2. Start bot.
3. In Telegram, tester sends `/start`.
4. Admin sends:

```text
/testsignal XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363
```

5. Tester receives a structured trade card.
6. Tester taps YES.
7. Backend creates exactly one command.
8. Simulator or MT5 EA polls `/commands/pending`.
9. Execution row is created.
10. Management events are posted: TP1, SL to breakeven, TP2, SL to TP1, TP3,
    FULLY_CLOSED.
11. Admin checks `/lastcommands`, `/lastsignals`, backend `/admin/status`, and
    database ledger if needed.

NO path:

- Tester taps NO.
- Backend creates a rejection approval.
- No command is created.

Duplicate path:

- Repeated YES returns existing approval/command and does not create another
  command.

Pause path:

- Admin `/pause` sets `admin_paused=true`.
- YES is blocked while paused.
- Admin `/resume` restores command creation.

## Screenshot Provider Flow

This is an extension beyond the first v1 build prompt.

Setup:

```env
SIGNAL_PROVIDER_INVITE_CODE=private-code-for-provider
SIGNAL_EXTRACTOR=claude
ANTHROPIC_API_KEY=real_key
```

Provider actions:

1. Provider sends `/provider private-code-for-provider`.
2. Provider sends `/start`.
3. Provider sends a chart/signal screenshot.
4. Bot replies with extracted candidate signal and parser result.
5. Provider taps Confirm, Edit, or Cancel.
6. Confirm calls `/signals/create`.
7. Only if parser returns VALID does the bot broadcast a trade card.

Safety note:

- Vision extraction is never an execution authority.
- It only generates candidate text for human review.
- The deterministic parser still rejects unsafe/ambiguous values.
- The tester still must press YES before any EA command exists.

## Backend API Map

Public/local:

- `GET /health`
- `POST /register_user`

Signal/provider/admin:

- `POST /signals/create`
- `POST /signals/extract`
- `GET /signals/recipients`
- `GET /signals/recent`
- `POST /signals/{signal_id}/approve`
- `POST /signals/{signal_id}/reject`

EA:

- `GET /commands/pending`
- `POST /commands/{command_id}/received`
- `POST /commands/{command_id}/execution`
- `POST /commands/{command_id}/management_event`
- `GET /ea/heartbeat`

Admin:

- `POST /admin/pause`
- `POST /admin/resume`
- `GET /admin/status`
- `GET /admin/users`
- `POST /admin/users/{telegram_user_id}/issue_license`
- `POST /admin/users/{telegram_user_id}/activate`
- `POST /admin/users/{telegram_user_id}/deactivate`

Auth:

- EA endpoints require `X-EA-API-Key`.
- Admin endpoints require `X-Admin-Id` matching `ADMIN_TELEGRAM_IDS`.
- Provider endpoints allow admin or `X-Signal-Provider-Id` matching
  `SIGNAL_PROVIDER_TELEGRAM_IDS`. The bot may proxy locally enrolled providers
  via the first admin id when configured.

## Core Code Pointers

Read in this order:

1. `AGENTS.md` - full original build spec and acceptance criteria.
2. `README.md` - user-facing overview and run instructions.
3. `backend/app/models.py` - SQLAlchemy schema.
4. `backend/app/crud.py` - safety-critical business logic.
5. `backend/app/parser.py` - deterministic signal parser.
6. `backend/app/ledger.py` - performance ledger updates.
7. `backend/app/routes/*.py` - API surface.
8. `telegram_bot/handlers.py` and `telegram_bot/keyboards.py` - Telegram UX.
9. `simulator/ea_simulator.py` - no-MT5 execution lifecycle.
10. `mt5_ea/SignalGateEA.mq5` and `mt5_ea/README_MT5_SETUP.md` - MT5 side.
11. `backend/tests/*.py` - current expected behavior.

## Split-Ticket Demo Partial Mode

The spec originally mentions fixed 0.01 lot and 50/25/25 partial closes. That is
not broker-compatible for many symbols because a 0.01 minimum lot cannot be
partially closed into 0.005 or 0.0025 lots.

Current v1 default:

```env
SPLIT_TICKET_DEMO_PARTIAL_MODE=true
TP1_LOT=0.02
TP2_LOT=0.01
TP3_LOT=0.01
DEFAULT_LOT_SIZE=0.01
```

Behavior:

- Open three child positions linked to one `command_id`.
- TP1 child: 0.02 lots, closes at TP1, then remaining SLs move to breakeven.
- TP2 child: 0.01 lots, closes at TP2, then TP3 SL moves to TP1.
- TP3 child: 0.01 lots, closes at TP3, then command becomes FULLY_CLOSED.
- Total demo exposure is 0.04 lots.

This is intentional and must remain transparent in code/docs.

## Known Limitations And Risks

- Auth is intentionally lightweight for local prototype use.
- Sequential ID generation via table counts is fine locally but not production
  concurrency-safe.
- SQLite is local-demo storage. Hosted mode should use PostgreSQL.
- MT5 demo/live detection depends on broker-reported `ACCOUNT_TRADE_MODE`;
  keep `DemoOnlyMode=true` and attach only to demo accounts.
- The MQL5 EA uses simple deterministic JSON extraction for the backend command
  shape rather than an external JSON library.
- Telegram broadcast assumes a private chat where Telegram user id can be used
  as chat id. This is acceptable for local testers but may need stored chat ids
  for real multi-user operation.
- Ledger R calculations are approximate/provisional when entry price is missing.
- Screenshot/chart-zone extraction is inherently interpretive. The bot must
  keep the preview-and-confirm gate.
- `.env.example` defaults `SIGNAL_EXTRACTOR=claude`; for offline local testing,
  set it to `fake`.

## Next Agent Instructions

If continuing the build:

1. Start by running `git status --short --branch`.
2. Do not touch or print `.env`.
3. Read `AGENTS.md` and this file.
4. Run the backend test suite before making changes.
5. Preserve every demo-only and idempotency invariant.
6. Do not add live trading, auto-copying, payment, public landing pages, React
   dashboards, Docker, Celery, Redis, or unrelated product features.
7. Keep raw Telegram/screenshot text out of MT5.
8. Keep route logic thin; business rules belong in `crud.py` or small services.
9. Any screenshot extraction changes must remain preview-only and parser-gated.
10. Any EA changes must report both success and failure states back to backend.

If preparing a clean transfer:

```bash
git status --short --branch
python -m pytest -q  # from backend venv
git add CODEX_HANDOFF.md backend/tests/conftest.py
git commit -m "Add Codex handoff and deterministic extractor tests"
git status --short --branch
```

Then share the git repo or a zip made from tracked files only. Do not include
`.env`, `.venv`, `backend/signalgate.db`, caches, or local settings.

