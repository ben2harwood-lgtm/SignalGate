# Codex Task Prompt — Compile & Demo-Test the SignalGate MT5 EA (macOS)

Paste everything in the `--- PROMPT ---` block below into Codex (or any
computer-controlling agent) running on **Ben's Mac**. It gets the SignalGate
Expert Advisor compiled and demo-tested end-to-end, and verifies the safety
fixes that could not be compiled where they were written.

**Context for the human (Ben):** the backend + Telegram bot are already running
on this Mac and the full Telegram flow works. What's left is the *real*
MetaTrader piece: compile the EA, put it on a **demo** MT5 account, and prove it
executes and — critically — records a stop-out as a **loss**, not a win. That
last part is the whole point; the EA has never been verified on a live terminal,
and until it is, the simulator (not the EA) is the safe path for any live demo.

---------------------------------- PROMPT ----------------------------------

## Role & mission

You are a build-and-test engineer with control of this Mac. Your mission:
**compile the SignalGate MetaTrader 5 Expert Advisor cleanly, run it on a demo
account, and verify it end-to-end**, then report results. Work autonomously;
only stop to ask the human on a hard blocker (can't install MT5, no demo account
possible, or a compile error you can't fix without changing trading logic).

## NON-NEGOTIABLE SAFETY RULES (read first)

1. **DEMO ACCOUNT ONLY.** Never log into, attach to, or trade a live account. If
   the only account available is live, STOP and report — do not proceed.
2. Keep the EA input `DemoOnlyMode = true` at all times. The EA is built to
   refuse live accounts; do not bypass that.
3. Do not change any trade-execution logic to "make a test pass." Fix only
   genuine **compile** errors (a typo, a build-version enum name). If a fix would
   change what a trade *does*, STOP and report it for human review.
4. Demo exposure is tiny by design (~0.04 lots total). Do not increase lot sizes.
   Do not remove the stop loss from any order.

## This Mac's actual setup (already true — verify, don't rebuild)

- The SignalGate project is at **`~/SignalGate`** (an unzipped copy, **not** a git
  checkout — so there's no `git pull` here; just use the files in place). The EA
  is `~/SignalGate/mt5_ea/SignalGateEA.mq5`.
- The backend is a Python app that runs **natively on this Mac**, so from MT5 it's
  reachable at **`http://127.0.0.1:8000`**. It may already be running (Ben starts
  it via `Start Backend.command`). The Mac's Python is the stock **3.9**.
- Config values you'll need (from `~/SignalGate/.env`):
  - **`EA_API_KEY = local-demo-ea-key`**
  - **admin id (`X-Admin-Id`) = `1483551673`**
- **Network note:** this Mac's home Wi-Fi blocks Telegram, so Ben runs the bot on
  an iPhone hotspot. **The EA test does not care** — the EA ↔ backend link is pure
  localhost (`127.0.0.1`), and you drive everything below with `curl`, no Telegram
  involved. Run the EA test on whatever network; ignore any Telegram-send errors
  in the backend log (harmless — the DB/ledger is the source of truth here).
- If you fix `SignalGateEA.mq5`, you **cannot** `git push` (not a checkout).
  Instead include the **full diff** in your report so it can be applied upstream.

Let `REPO = ~/SignalGate` and `EA = $REPO/mt5_ea/SignalGateEA.mq5`.

## Phase 0 — Backend up + a dedicated EA test user

1. Confirm the backend is up: `curl -s http://127.0.0.1:8000/health` →
   `{"status":"ok","demo_only_mode":true,...}`. If it's not up, start it:
   ```
   cd $REPO/backend && source .venv/bin/activate
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   (The venv already has the deps installed. If for some reason it doesn't:
   `grep -viE pytest requirements.txt > /tmp/r.txt && pip install -r /tmp/r.txt`
   — pytest is pinned to a version that needs Python 3.10+, skip it, it's
   test-only.)
2. **Register a dedicated EA test user and capture its id** (keeps this separate
   from Ben's phone, which is already `USER-000001`):
   ```
   curl -s -X POST http://127.0.0.1:8000/register_user \
     -H 'Content-Type: application/json' \
     -d '{"telegram_user_id":"ea-tester","first_name":"EA Tester"}'
   ```
   Read the returned `"id"` (e.g. `USER-000002`). Call it **`EA_USER`**. You'll
   set the EA's `UserID` input to this exact value, and approve test signals with
   `telegram_user_id: "ea-tester"`.

## Phase 1 — Install MT5 (if needed) & compile the EA

1. If MetaTrader 5 is not installed, install the official **MetaTrader 5 for Mac**
   from metatrader5.com (it bundles its own Wine; MetaEditor comes with it). Do
   not install random broker forks unless Ben specifies one.
2. In MT5: **File → Open Data Folder**. The EA must live in
   `<data folder>/MQL5/Experts/`. Copy it: `cp "$EA" "<data folder>/MQL5/Experts/"`.
3. Open **MetaEditor** (Tools → MetaQuotes Language Editor / F4). Open
   `Experts/SignalGateEA.mq5`. Press **F7** (Compile). Read **Toolbox → Errors**.
4. PASS = **0 errors** (list any warnings); a `SignalGateEA.ex5` appears next to
   the `.mq5`. Compile errors are almost certainly mechanical (a typo, an MQL5
   build-version enum/function name). Fix only those in `$EA`, recompile, and
   record exactly what you changed as a diff. If a fix would change trade
   behavior, STOP and report.

## Phase 2 — Demo terminal setup

1. **Log into a demo account**: File → Open an Account → MetaQuotes Demo (or a
   broker demo) → create/log in. Confirm it is **Demo** (play-money balance;
   Journal says demo). Note the **margin mode** (Hedging vs Netting) from the
   login Journal line — you'll cross-check the EA's fallback in Test 3.
2. **Whitelist WebRequest**: Tools → Options → **Expert Advisors** → tick "Allow
   WebRequest for listed URL" and add exactly **`http://127.0.0.1:8000`** (no
   trailing slash). Also tick "Allow algorithmic trading".
3. **Enable algo trading**: the toolbar **Algo Trading** button is green (Ctrl+E).
4. Open a **`BTCUSD`** chart (crypto trades 24/7, so tests work any day). Open a
   **`XAUUSD`** chart too (metals close on weekends — used for the market-closed
   test).
5. **Attach the EA** to the BTCUSD chart (drag from Navigator → Expert Advisors).
   Set inputs:
   - `BackendURL` = `http://127.0.0.1:8000`
   - `UserID` = **`EA_USER`** (the id you captured in Phase 0)
   - `EAApiKey` = `local-demo-ea-key`
   - `DemoOnlyMode` = `true`
   - `EnableTrading` = `true`
   - `SymbolOverride` = your broker's BTC symbol if it isn't plain `BTCUSD`
     (check Market Watch — some use `BTCUSD.x` etc.)
   A smiley on the chart = running. Check **Toolbox → Experts** for the EA's
   startup lines (heartbeat; on a netting account, a "falling back to
   single-ticket mode" warning).

## Phase 3 — Drive the backend with curl (no Telegram)

`AID = 1483551673`. Repeat the helper with different signal text per test.

**Create + approve a signal for the EA's user:**
```
SIG=$(curl -s -X POST http://127.0.0.1:8000/signals/create \
  -H 'Content-Type: application/json' -H "X-Admin-Id: 1483551673" \
  -d '{"raw_text":"<SIGNAL TEXT>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
curl -s -X POST http://127.0.0.1:8000/signals/$SIG/approve \
  -H 'Content-Type: application/json' -d '{"telegram_user_id":"ea-tester"}'
```
The approval returns a `command_id`. The EA on the BTCUSD chart polls every ~2s
and picks it up. Read the live BTC price off the chart so your SL/TP levels are
realistic and correctly ordered.

## Phase 4 — Verification matrix (the point of the task)

After each test, inspect state three ways:
- Counts: `curl -s http://127.0.0.1:8000/admin/status -H "X-Admin-Id: 1483551673"`
- **Ledger (the honest record):**
  `curl -s "http://127.0.0.1:8000/admin/ledger" -H "X-Admin-Id: 1483551673" | python3 -m json.tool`
- Command status:
  ```
  cd $REPO/backend && ./.venv/bin/python -c "from app.database import SessionLocal; from app import models; db=SessionLocal(); [print(c.id, c.status, c.last_error) for c in db.query(models.Command).all()]"
  ```

**Test 1 — Clean compile.** Done in Phase 1. PASS = 0 errors + `.ex5`.

**Test 2 — Market-closed is reported honestly.**
When XAUUSD is closed (weekend), create+approve an **XAUUSD** signal near a
plausible gold price, correctly ordered, e.g.
`XAUUSD BUY SL 2320 TP1 2360 TP2 2370 TP3 2380`. Point an EA instance at the
XAUUSD chart (same inputs).
- PASS = command ends `FAILED` with `last_error` ~ `MARKET_CLOSED`, ledger row
  `FAILED` — **NOT** `EXECUTED_OPEN`, **NOT** any TP hit.
- FAIL = a TP win / `EXECUTED_OPEN` for a market that never opened (old bug).

**Test 3 — Normal BTCUSD trade opens WITH a stop (sanity).**
Approve a BTCUSD signal, SL below and TPs above current price, e.g. (BTC ≈ 60000)
`BTCUSD BUY SL 59000 TP1 60800 TP2 61500 TP3 62500`.
- PASS = command → `EXECUTED_OPEN`; in MT5 each child position **has a stop loss
  set**; ledger → `EXECUTED_OPEN`. Hedging account → 3 positions; netting account
  → 1 position + a single-ticket-fallback note in the Experts log.
Don't manually close it.

**Test 4 — Stop-out is recorded as a LOSS, not a win. ★ THE KEY TEST**
Approve a BTCUSD signal with a **tight** stop just below price so a normal dip
triggers it, e.g. (BTC ≈ 60000) `BTCUSD BUY SL 59960 TP1 60600 TP2 61000 TP3
61500`. Wait for price to touch the stop (minutes, be patient). When it closes:
- PASS = a `STOP_LOSS_HIT` event is recorded, command ends `FULLY_CLOSED`, and the
  **ledger `result_status` is `STOPPED_OUT` with negative R** — never a TP hit.
- If the market is too flat to hit the stop in reasonable time, document that, and
  separately confirm the backend's stop-out path with the simulator (exercises
  the ledger, not the EA's deal read):
  ```
  cd $REPO && ./backend/.venv/bin/python simulator/ea_simulator.py \
    --user-id <a fresh USER-id> --api-key local-demo-ea-key --scenario stop_out --once
  ```
  (register that user and approve a fresh signal for it first). Ledger must show
  `STOPPED_OUT`, R = -1.0.

**Test 5 — LIMIT orders are refused.**
Approve a signal with an explicit entry price, e.g.
`BTCUSD BUY Entry: 60000 SL 59000 TP1 61000 TP2 62000`.
- PASS = command ends `FAILED` with `last_error` ~ `UNSUPPORTED_ENTRY_TYPE`; **no**
  order placed.

## Acceptance criteria (report PASS/FAIL for each)

- [ ] EA compiles with **0 errors** (list warnings) and produces `.ex5`.
- [ ] Test 2: closed-market XAUUSD → `FAILED / MARKET_CLOSED`, not a win.
- [ ] Test 3: BTCUSD opens position(s), **each with a stop loss**; correct
      hedging(3)/netting(1+fallback) behavior for the account.
- [ ] Test 4: a real stop-out → `STOP_LOSS_HIT` + ledger `STOPPED_OUT` (negative
      R), **never** a TP win. (Or simulator-confirmed, with the live reason noted.)
- [ ] Test 5: LIMIT → `FAILED / UNSUPPORTED_ENTRY_TYPE`, no order placed.
- [ ] At no point did the EA touch a live account.

## Report back

Give Ben a short report: MT5 build number, account type (demo, hedging/netting),
the compile result (errors/warnings), any code fixes as a **diff** (since this
isn't a git checkout, paste the diff — don't push), and the PASS/FAIL table with
the ledger/command output you observed for each test. Flag clearly whether the
EA is now trustworthy enough to show in a live demo, or whether the simulator
should remain the demo path.

-------------------------------- END PROMPT --------------------------------
