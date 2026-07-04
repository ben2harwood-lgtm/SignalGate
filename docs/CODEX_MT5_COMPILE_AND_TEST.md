# Codex Task Prompt — Compile & Demo-Test the SignalGate MT5 EA (macOS)

Paste everything in the `--- PROMPT ---` block below into Codex (or any
computer-controlling coding agent) running on the Mac that has MetaTrader 5
installed. It compiles `mt5_ea/SignalGateEA.mq5` and demo-tests it end-to-end,
verifying the safety fixes that could not be compiled in the environment where
they were written.

Context for you (the human): the EA was recently changed to (a) verify order
fills by retcode so a rejected/closed-market order is not reported as a success,
(b) detect real stop-outs via the broker's deal reason and report `STOP_LOSS_HIT`
instead of a fake TP win, (c) fall back to single-ticket mode on a netting
account, and (d) refuse LIMIT commands. None of this was compilable on Linux.
This task proves it works on a real demo account.

---------------------------------- PROMPT ----------------------------------

## Role & mission

You are a build-and-test engineer with control of this Mac. Your mission is to
**compile the SignalGate MetaTrader 5 Expert Advisor cleanly and demo-test it
end-to-end**, then report results. Work autonomously; only stop to ask a human
if you hit a hard blocker (no MT5 installed, no demo account possible, or a
compile error you cannot resolve without changing trading logic).

## NON-NEGOTIABLE SAFETY RULES (read first)

1. **DEMO ACCOUNT ONLY.** Never log into, attach to, or trade a live account.
   If the only available account is live, STOP and report — do not proceed.
2. Keep the EA input `DemoOnlyMode = true` at all times. The EA is designed to
   refuse live accounts; do not attempt to bypass that.
3. Do not change any trade-execution logic to "make a test pass." You may fix
   only genuine compile errors (typos, a missing include). If a fix touches
   trading behavior, stop and report it for human review instead.
4. Total demo exposure is tiny by design (~0.04 lots). Do not increase lot
   sizes. Do not remove the stop loss from any order.

## Environment (assume, then verify)

- macOS with **MetaTrader 5 installed** (the MetaQuotes Mac app or a broker
  build). MetaEditor is included with it.
- The SignalGate repo is checked out locally on this Mac, on branch
  `claude/signalgate-full-audit-bjh0tk`. If unsure of the path, find it:
  `find ~ -name SignalGateEA.mq5 -not -path '*/.Trash/*' 2>/dev/null`.
- The **backend runs natively on the Mac** (Python), so from inside MT5 the
  backend is reachable at `http://127.0.0.1:8000`.
  - If it turns out MT5 is running inside a Parallels/VMware Windows VM (not the
    Mac Wine app), the backend is NOT at 127.0.0.1 from inside the VM — use the
    Mac's host IP (Parallels default `http://10.211.55.2:8000`) for `BackendURL`
    and the WebRequest whitelist. Detect this and adjust.

Let `REPO` = the repo root you found. Let `EA` = `$REPO/mt5_ea/SignalGateEA.mq5`.

## Phase 0 — Prep the backend (native Mac terminal)

1. `cd $REPO && git fetch origin && git checkout claude/signalgate-full-audit-bjh0tk && git pull`
2. Start the backend. Easiest: double-click `Start Backend.command`, OR in a
   terminal:
   ```
   cd $REPO/backend
   python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
   cp -n ../.env.example .env   # if no .env exists yet
   ./.venv/bin/python ../scripts/init_db.py
   ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
3. Confirm it's up: `curl -s http://127.0.0.1:8000/health` returns
   `{"status":"ok","demo_only_mode":true,...}`.
4. Read the two values you'll need from `$REPO/backend/.env` (or `.env.example`):
   - `EA_API_KEY` (default `local-demo-ea-key`)
   - `ADMIN_TELEGRAM_IDS` (default `123456789`) — the first id is your admin id.

## Phase 1 — Compile the EA

**Primary path (GUI — most reliable on the Mac app):**
1. In MT5, click **File → Open Data Folder**. Note the path; the EA must live in
   `<data folder>/MQL5/Experts/`. Copy it there if needed:
   `cp "$EA" "<data folder>/MQL5/Experts/"`.
2. Open **MetaEditor** (Tools → MetaQuotes Language Editor, or F4 from the
   terminal). Open `Experts/SignalGateEA.mq5`.
3. Press **F7** (Compile). Read the **Toolbox → Errors** tab.
4. Acceptance for this phase: **0 errors** (warnings are acceptable but list
   them). A `SignalGateEA.ex5` file must appear next to the `.mq5`.

**Optional CLI path (if the app exposes metaeditor64.exe via its wine bottle):**
`"<path>/metaeditor64.exe" /compile:"<data folder>\MQL5\Experts\SignalGateEA.mq5" /log:compile.log`
then read `compile.log` for the `0 errors, 0 warnings` line. Only use this if you
can locate the executable; otherwise use the GUI.

**If there are compile errors:** they are almost certainly a mechanical issue
(a typo, or an MQL5 build-version difference in an enum/function name), NOT a
logic problem. Fix only mechanical issues in `$REPO/mt5_ea/SignalGateEA.mq5`,
recompile, and record exactly what you changed. If an error would require
changing what a trade does, STOP and report it verbatim.

## Phase 2 — Set up the demo terminal

1. **Open a demo account**: File → Open an Account → choose MetaQuotes Demo (or
   your broker's demo) → create/log in. Verify the account is **Demo** (the
   Journal/Account line says demo; balance is play money).
2. Note the account's **margin mode** (Hedging vs Netting) — you'll cross-check
   the EA's fallback behavior later. (Tools → the account info, or the Journal
   at login.)
3. **Whitelist WebRequest**: Tools → Options → **Expert Advisors** →
   tick "Allow WebRequest for listed URL" and add **`http://127.0.0.1:8000`**
   (or the Parallels host URL if applicable). Exactly, no trailing slash.
4. **Enable algo trading**: toolbar **Algo Trading** button green (Ctrl+E), and
   in the same Options tab tick "Allow algorithmic trading".
5. **Open a `BTCUSD` chart** (crypto trades 24/7, so it works this weekend). Also
   open a `XAUUSD` chart — metals are closed on weekends, which you'll use to
   test the market-closed path.
6. **Attach the EA** to the BTCUSD chart (drag SignalGateEA from Navigator →
   Experts). In its inputs set:
   - `BackendURL` = `http://127.0.0.1:8000` (or Parallels host URL)
   - `UserID` = `USER-000001` (you register this user in Phase 3)
   - `EAApiKey` = the `EA_API_KEY` you read from `.env`
   - `DemoOnlyMode` = `true`
   - `SymbolOverride` = your broker's BTC symbol if it isn't plain `BTCUSD`
     (check Market Watch; some brokers use `BTCUSD.x`, etc.)
   A smiley face on the chart = running. Check the **Experts** log tab for the
   EA's startup lines (it prints a heartbeat and, on a netting account, a
   "falling back to single-ticket mode" warning).

## Phase 3 — Drive the backend (no Telegram needed)

Do all of this with `curl` against `http://127.0.0.1:8000`. Substitute the admin
id and EA key you read from `.env`. `AID` = admin id, `KEY` = EA_API_KEY.

1. **Register the EA's user** (first registration → `USER-000001`):
   ```
   curl -s -X POST http://127.0.0.1:8000/register_user \
     -H 'Content-Type: application/json' \
     -d '{"telegram_user_id":"1","first_name":"EA Tester"}'
   ```
   Confirm the returned `"id"` is `USER-000001` (matches the EA's `UserID`).

2. **Helper to create + approve a signal** (repeat with different text):
   ```
   SIG=$(curl -s -X POST http://127.0.0.1:8000/signals/create \
     -H 'Content-Type: application/json' -H "X-Admin-Id: <AID>" \
     -d '{"raw_text":"<SIGNAL TEXT>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
   curl -s -X POST http://127.0.0.1:8000/signals/$SIG/approve \
     -H 'Content-Type: application/json' -d '{"telegram_user_id":"1"}'
   ```
   Approval returns a `command_id` (e.g. `CMD-000001`). The EA on the BTCUSD
   chart polls every ~2s and will pick it up.

3. **Read the current BTC price** so your stop-loss levels are realistic — check
   Market Watch, or `curl` a public price, or just read it off the chart. You
   need signals whose SL is on the correct side of price and TP levels ordered.

## Phase 4 — Verification matrix (this is the point of the task)

Run these and record the outcome of each. After each, inspect state with:
- `curl -s http://127.0.0.1:8000/admin/status -H "X-Admin-Id: <AID>"`
  (watch `counts.executions` / `counts.management_events`), and
- the ledger, read directly from the DB:
  ```
  cd $REPO/backend && ./.venv/bin/python -c "from app.database import SessionLocal; from app import models; db=SessionLocal(); [print(l.signal_id, l.command_id, l.result_status, 'R=',l.r_result, '|', l.final_notes) for l in db.query(models.PerformanceLedger).all()]"
  ```
- and the command status:
  ```
  cd $REPO/backend && ./.venv/bin/python -c "from app.database import SessionLocal; from app import models; db=SessionLocal(); [print(c.id, c.status, c.last_error) for c in db.query(models.Command).all()]"
  ```

**Test 1 — Clean compile.** Already done in Phase 1. PASS = 0 errors + `.ex5`.

**Test 2 — Market-closed is reported honestly (verifies P0-5).**
While XAUUSD is closed (weekend), create+approve an **XAUUSD** signal, e.g.
`XAUUSD BUY SL 2320 TP1 2360 TP2 2370 TP3 2380` (adjust to be near a plausible
gold price and correctly ordered). Attach a second EA instance to the XAUUSD
chart with the same inputs, or temporarily point the running EA at XAUUSD.
- PASS = the command ends `FAILED` with `last_error` like `MARKET_CLOSED`, and
  the ledger row is `FAILED` — **NOT** `EXECUTED_OPEN` and **NOT** any TP hit.
- FAIL = the ledger shows a TP win / `EXECUTED_OPEN` for a market that never
  opened (that would be the old fake-success bug).

**Test 3 — Normal BTCUSD trade opens with a stop (sanity).**
Create+approve a BTCUSD signal with SL below and TPs above current price, e.g.
(if BTC ≈ 60000) `BTCUSD BUY SL 59000 TP1 60800 TP2 61500 TP3 62500`.
- PASS = command → `EXECUTED_OPEN`; in MT5 you see the child position(s) each
  **with a stop loss set**; ledger row → `EXECUTED_OPEN`. On a hedging account
  you should see 3 positions; on a netting account 1 position and a
  single-ticket fallback note in the Experts log (verifies **P1-14**).
Let it run or close it via a stop-out in Test 4; don't manually close it.

**Test 4 — Stop-out is recorded as a LOSS, not a win (verifies P0-4). ★ key test**
Create+approve a BTCUSD signal with a **tight** stop just below current price so
a normal dip triggers it, e.g. (if BTC ≈ 60000) `BTCUSD BUY SL 59960 TP1 60600
TP2 61000 TP3 61500`. Wait for price to touch the stop (BTC moves; be patient —
minutes, not seconds). When the position(s) close on the stop:
- PASS = a `STOP_LOSS_HIT` management event is recorded, the command ends
  `FULLY_CLOSED`, and the **ledger `result_status` is `STOPPED_OUT` with a
  negative R** — never `TP1_HIT/TP2_HIT/TP3_HIT`.
- If the market is too flat to hit the stop in a reasonable time, document that,
  and separately confirm the backend/ledger stop-out path with the simulator
  (this exercises the ledger, though not the EA's deal-reason read):
  ```
  cd $REPO && ./backend/.venv/bin/python simulator/ea_simulator.py \
    --user-id USER-000002 --api-key <KEY> --scenario stop_out --once
  ```
  (register a `USER-000002` and approve a fresh signal for it first). Ledger
  must show `STOPPED_OUT`, R = -1.0.

**Test 5 — LIMIT orders are refused (verifies P1-16).**
Create+approve a signal with an explicit entry price (LIMIT), e.g.
`BTCUSD BUY Entry: 60000 SL 59000 TP1 61000 TP2 62000`.
- PASS = the command ends `FAILED` with `last_error` ~ `UNSUPPORTED_ENTRY_TYPE`;
  **no** market order was placed.

## Acceptance criteria (report PASS/FAIL for each)

- [ ] EA compiles with **0 errors** (list any warnings) and produces `.ex5`.
- [ ] Test 2: closed-market XAUUSD command → `FAILED / MARKET_CLOSED`, not a win.
- [ ] Test 3: BTCUSD command opens position(s), **each with a stop loss**;
      correct hedging(3)/netting(1-with-fallback) behavior for the account.
- [ ] Test 4: a real stop-out → `STOP_LOSS_HIT` + ledger `STOPPED_OUT` (negative
      R), **never** a TP win. (Or simulator-confirmed with a documented reason
      the live stop couldn't be triggered.)
- [ ] Test 5: LIMIT signal → `FAILED / UNSUPPORTED_ENTRY_TYPE`, no order placed.
- [ ] At no point did the EA touch a live account.

## Report back

Produce a short report with: the exact repo path and commit SHA
(`git rev-parse HEAD`), MT5 build number, account type (demo, hedging/netting),
the compile log (errors/warnings), any code fixes you made (as a diff), and the
PASS/FAIL table above with the ledger/command output you observed for each test.
If you changed `SignalGateEA.mq5`, commit it on the same branch with a clear
message and note it in the report — do not push to any other branch.

-------------------------------- END PROMPT --------------------------------
