# Local Setup

Prerequisites: Python 3.9+ and (optionally) MetaTrader 5 on a demo account.

## 0. Configure environment

```bash
cp .env.example .env
# Edit .env:
#   - TELEGRAM_BOT_TOKEN  (from @BotFather) — only needed to run the bot
#   - ADMIN_TELEGRAM_IDS  (your numeric Telegram user id)
#   - EA_API_KEY          (any shared secret; must match the EA input)
```

`.env` is git-ignored. Never commit real tokens.

## 1. Backend (Terminal 1)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python ../scripts/init_db.py          # create tables + seed settings
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Local identity-header authentication is loopback-only by configuration.** When
`REQUIRE_LICENSE=false`, startup now refuses explicitly non-loopback
`BACKEND_HOST` or `BACKEND_BASE_URL` values, including public domains and
all-interface binds. Keep both pointed at `127.0.0.1`, `::1` or `localhost`.
This remains a **partial** issue #108 defence. In addition to
configuration checks, local-demo HTTP requests are now refused before route
dispatch unless the actual ASGI-bound server address **and** request `Host`
are both loopback. This catches a direct `uvicorn --host 0.0.0.0` override
and ordinary reverse proxies retaining the public `Host`, even if
`BACKEND_HOST` was configured safely. TestClient checks are **synthetic** and
do not prove real listener or proxy isolation.

**Never publish the local identity-header API externally.** A reverse proxy
that rewrites `Host` to loopback can still conceal its public exposure; custom
ASGI servers may not supply a trusted bound address. Use the separate licensed
HTTPS/PostgreSQL configuration for a controlled hosted demo only after
independent ingress/security and other external gate acceptance. No MT5 broker,
customer, production or live trading acceptance is inferred.

Check it: open http://127.0.0.1:8000/health → should show
`{"status":"ok","demo_only_mode":true,"admin_paused":false}`.
Interactive API docs: http://127.0.0.1:8000/docs

**Database bootstrap safety:** `scripts/init_db.py` and
`scripts/seed_settings.py` preflight the current configuration **before
importing the database engine**. With `REQUIRE_LICENSE=false`, they refuse
PostgreSQL (`postgres://` or `postgresql://`), non-file SQLite, and
`DEMO_ONLY_MODE=false`; they accept only file-backed local SQLite.
A correctly configured `REQUIRE_LICENSE=true` hosted invocation still checks
the current Alembic migration state before seeding. Neither script is a hosted
schema migration tool; use the reviewed Alembic process for hosted upgrades.

This is a **partial** mitigation of [issue #108](https://github.com/ben2harwood-lgtm/SignalGate/issues/108), alongside the separately proposed direct `init_db()` guard (#125) and local HTTP ingress refusal (#126). These checks do **not** prove reverse-proxy/public-network isolation or external acceptance. Retain `REQUIRE_LICENSE=false` only on an actually private loopback demo.

## 2. Telegram bot (Terminal 2)

```bash
cd telegram_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_bot.py
```

In Telegram: send `/start` to your bot to register.

## 3a. EA simulator (Terminal 3, no MetaTrader needed)

```bash
# from the project root
python simulator/ea_simulator.py --user-id USER-000001 --api-key local-demo-ea-key
```

Or run the whole scripted flow at once (registers, signals, approves,
simulates):

```bash
python simulator/run_demo_flow.py --admin-id <YOUR_ADMIN_ID> --api-key local-demo-ea-key
```

## 3b. MetaTrader 5 EA (instead of the simulator)

See `mt5_ea/README_MT5_SETUP.md`. Summary:
1. Copy `SignalGateEA.mq5` into `MQL5/Experts` and compile (F7).
2. Tools → Options → Expert Advisors → allow WebRequest for
   `http://127.0.0.1:8000`.
3. Enable Algo Trading, attach to a **demo** XAUUSD chart, set `UserID` and
   `EAApiKey`.

## 4. Run the tests

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

## Useful scripts

- `scripts/init_db.py` — create tables + seed settings.
- `scripts/seed_settings.py` — (re)seed default settings only.
- `scripts/reset_local_db.py` — drop everything and recreate (LOCAL ONLY).
