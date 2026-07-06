# SignalGate — Demo Day Runbook (Nick's live walkthrough)

**Goal of the session:** Nick sends a signal screenshot from his own phone, watches
the bot read it, confirms it, a tester taps **Approve**, and everyone watches a demo
trade execute and fill an audit ledger end to end — with no live money anywhere.

This is the **"Watch It Work"** onboarding from the marketing plan, run for real.

> **This runbook uses the simulator, not the MT5 EA.** The Python simulator is the
> safe, verified demo path today. The MT5 Expert Advisor has not been compiled or
> run on a broker terminal yet (see `docs/CODEX_MT5_COMPILE_AND_TEST.md`), and the
> audit flagged that an unverified EA can mislabel a stop-out as a win in the ledger.
> Do **not** put the EA in front of Nick tomorrow. Demo the simulator; it drives the
> exact same backend, cards, and ledger.

---

## 0. The one-sentence topology (read this first)

**Everything technical runs on Ben's laptop.** Nick and the tester only ever touch
**Telegram** on their own phones. Nick's phone does **not** connect to the backend —
his screenshot goes to the Telegram bot, and the bot (on Ben's laptop) talks to the
backend. So "works from Nick's side" means one thing: **the bot is online and Nick has
provider access.** That's it.

```
Nick's phone (Telegram)  ─┐
Tester's phone (Telegram) ─┼──►  Telegram bot  ──►  Backend  ──►  Simulator
Ben's laptop (Telegram)  ─┘        (Ben's laptop, all three processes local)
```

Three windows stay open on Ben's laptop for the whole demo:
1. **Backend** (`Start Backend.command`)
2. **Telegram bot** (`Start Bot.command`)
3. **Simulator** (one command, run when the tester taps YES)

---

## 1. Pre-flight checklist — do this the night before, not at the door

Tick every box. The ones marked **CRITICAL** are the ones that silently ruin the demo.

### CRITICAL — screenshot reading will be fake without this
- [ ] **`ANTHROPIC_API_KEY` is set to a real `sk-ant-...` key in `.env`.**
      Without it, `SIGNAL_EXTRACTOR=claude` cannot read the image and (if left on
      `fake`) the bot returns a **canned hard-coded signal that ignores Nick's
      screenshot entirely**. Nick will send EURUSD and see XAUUSD come back. Verify:
      ```bash
      grep -E "SIGNAL_EXTRACTOR=|ANTHROPIC_API_KEY=" .env
      # want: SIGNAL_EXTRACTOR=claude   and a real key, not "replace_me"
      ```
- [ ] **Do a real extraction test before Nick arrives.** Send one of Nick's actual
      screenshots to the bot yourself (as a File) and confirm the numbers come back
      right. Reading levels off a live chart is the riskiest step — rehearse it.

### CRITICAL — Nick must be a provider, not a tester
- [ ] **Nick has provider access.** Either his numeric Telegram id is in
      `SIGNAL_PROVIDER_TELEGRAM_IDS`, or set `SIGNAL_PROVIDER_INVITE_CODE` and have
      him send `/provider THE_CODE` at the start. Confirm with `/status` → it must say
      **`Role: screenshot provider`**. If it says `tester`, he can't submit screenshots.
- [ ] **Get Nick's numeric Telegram id ahead of time** (he sends `/status`, reads you
      the number) so you can add it and restart *before* he's watching.

### CRITICAL — there must be a registered tester to receive the card
- [ ] **At least one tester has sent `/start`** and you have their `USER-...` id.
      A confirmed signal broadcasts to *active testers*; with zero testers the card
      goes nowhere and the demo dead-ends. The tester can be:
      - the person Nick brought, on their own phone, **or**
      - Ben on a second Telegram account, **or**
      - Ben himself (Ben is admin *and* can register as a tester with `/start`).
- [ ] **Note the tester's USER id** — you'll pass it to the simulator.

### Backend / bot health
- [ ] `.env` has a real `TELEGRAM_BOT_TOKEN` (not `replace_me`).
- [ ] `DEMO_ONLY_MODE=true` (never change this).
- [ ] `ALLOWED_SYMBOLS` includes the pairs Nick actually trades — or is **empty**
      (empty = allow every pair the parser knows: all forex majors/minors/crosses,
      metals, crypto). If you restrict it, put Nick's real pairs in, e.g.
      `ALLOWED_SYMBOLS=EURUSD,GBPUSD,GBPJPY,USDJPY`. A pair not on the list is rejected.
- [ ] Backend health returns green:
      ```bash
      curl -s http://127.0.0.1:8000/health
      # {"status":"ok","demo_only_mode":true,"admin_paused":false}
      ```
- [ ] `admin_paused` is **false** (if a previous test left it paused, run `/resume`).
- [ ] Bot answers `/start` and `/status` in Telegram.

### After any `.env` change
- [ ] **Restart both the backend and the bot.** `.env` is read at startup only.

---

## 2. Start-up sequence (morning of, ~5 minutes)

On Ben's laptop, in order:

1. **Start the backend** — double-click `Start Backend.command` (Mac) or
   `Start Backend.bat` (Windows). Leave the window open. It prints
   `http://127.0.0.1:8000/health`. First run installs dependencies (a minute or two).
2. **Confirm health** in a browser or terminal:
   `curl -s http://127.0.0.1:8000/health` → expect `"status":"ok"`.
3. **Start the bot** — double-click `Start Bot.command` / `Start Bot.bat`. Leave it open.
4. **Smoke-test from Ben's phone:** `/start` then `/status`. Status should show backend
   reachable and `Admin paused: false`.
5. **Register the tester** (their phone or the second account): `/start`. Note the
   `USER-...` id it returns.
6. **Give Nick provider access** if not already: `/provider THE_CODE`, then he sends
   `/status` and you both confirm `Role: screenshot provider`.

You are now ready. Keep all windows open.

### 2b. Dry-run the engine before Nick arrives (30 seconds, do this)

With the backend running, prove the whole pipeline + honest ledger in one command —
no Telegram, no MT5. It drives a **winning** trade and a **losing** (stopped-out) trade
through the simulator and prints the ledger:

```bash
python simulator/quick_demo.py --admin-id 123456789 --api-key local-demo-ea-key
```
(`--admin-id` must be one of your `ADMIN_TELEGRAM_IDS`.) You should see a WIN row
(`TP3_HIT`, positive R) and a LOSS row (`STOPPED_OUT`, negative R). If that prints,
the backend, execution path, and ledger are all healthy. This is a confidence check,
**not** the Nick demo — it bypasses Telegram on purpose. Reset afterwards if you want a
clean slate (`python scripts/reset_local_db.py && python scripts/init_db.py`), then
re-register the tester.

---

## 3. The live demo script (the part Nick drives)

This mirrors the dress rehearsal that passed end to end. Narrate each step — the audit
trail filling in live is the whole spectacle.

| # | Who | Action | What everyone should see |
|---|-----|--------|--------------------------|
| 1 | **Nick** | In Telegram, tap 📎 → **File** → pick his signal screenshot → send | Bot replies *"Read from your screenshot: …"* with symbol, direction, SL, TP1–TP3, a confidence line, and a **"Price scale read:"** list of the numbers it saw on the axis |
| 2 | **Nick + Ben** | Read every number against the chart. Check the "Price scale read" list | Numbers match the screenshot |
| 3 | **Nick** | Tap **Confirm & Send** (or **Edit** to fix, or **Cancel**) | Bot: *"Signal SIG-… created and card sent to N tester(s)."* |
| 4 | **Tester** | Receives the trade card with **YES / NO** buttons; taps **YES: Place Demo Trade** | Bot: *"Approved. Waiting for MetaTrader EA to execute demo trade."* Exactly **one** command is created |
| 5 | **Ben** | In the third window, start the simulator for that tester (command below) | Simulator prints *"SIMULATOR ONLY — not trading"*, picks up the command, posts execution |
| 6 | **Everyone** | Watch the lifecycle | Simulator posts OPEN → TP1 close + SL→breakeven → TP2 close + SL→TP1 → TP3 close → **FULLY_CLOSED**; command status walks EXECUTED_OPEN → … → FULLY_CLOSED |
| 7 | **Ben** | Show the record — pull up the ledger live in a browser: `http://127.0.0.1:8000/admin/ledger` (send header `X-Admin-Id: <your admin id>`; or `/lastsignals` / `/lastcommands` in Telegram) | The signal, the one command, the execution, ~10 management events, and a ledger row with its `result_status` and R — the honest, timestamped record that is the product |

> **Showing the ledger in a browser:** `/admin/ledger` needs the admin header, so the
> simplest live view is a terminal one-liner you can run on the projector:
> `curl -s -H "X-Admin-Id: 123456789" http://127.0.0.1:8000/admin/ledger | python3 -m json.tool`
> (swap in your real admin id). It lists every trade's outcome — wins **and** losses.

**The simulator command for step 5** (replace the USER id with the tester's):
```bash
cd /path/to/SignalGate
python simulator/ea_simulator.py \
  --user-id USER-000001 \
  --api-key local-demo-ea-key \
  --backend http://127.0.0.1:8000
```
It auto-detects the pending command, plays the full winning lifecycle, and exits.
(`--api-key` must match `EA_API_KEY` in `.env`.)

> **Talking point for step 4→5:** "Nothing traded until the tester tapped Approve, and
> the tap created exactly one command — a duplicate tap can't create a second. Then a
> separate execution component picks it up. Raw signal text never reached the trading
> side; only the checked, approved command did."

---

## 4. Fallbacks (have these ready — don't improvise in front of Nick)

| If this breaks… | Do this instead |
|---|---|
| **Screenshot reads wrong numbers** | Nick taps **Edit** and types the corrected signal, e.g. `EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950 TP3 1.1000`. The parser re-checks it and the card goes out only if valid. This is a *feature* to show, not a failure — "the human confirms every number." |
| **Extraction is completely unreadable / API key problem** | Fall back to the admin typed path: Ben sends `/testsignal EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950 TP3 1.1000`. Same card, same downstream flow. Explain screenshot reading is the ingestion convenience; the deterministic parser is the safety boundary either way. |
| **Photo came through blurry** | Ask Nick to resend **as a File** (📎 → File), not as a photo. Telegram compresses "photo" uploads and blurs the price-scale digits — the #1 cause of misreads. The reader also auto-zooms the price axis, but a sharp source always wins. |
| **Card didn't reach the tester** | The tester probably isn't registered/active. Have them send `/start`, confirm you got a `USER-…` id, then Nick re-confirms (or re-run `/testsignal`). Check `admin_paused` is false. |
| **Backend paused from an earlier test** | `/resume` (admin), or `curl -s -X POST -H "X-Admin-Id: <your id>" http://127.0.0.1:8000/admin/resume`. |
| **A stale command is stuck `SENT_TO_EA`** | Admin reset: `POST /admin/commands/{id}/reset` re-queues it as PENDING for the simulator. |
| **Want to show an honest loss, not just a win** | Run the simulator with `--scenario stop_out` — it opens then gets stopped out, and the ledger records `STOPPED_OUT`. Powerful: proves the record shows losses, not just wins. |
| **Wi-Fi flaky for the API call** | Do the pre-flight extraction test the night before on a good connection; keep the typed `/testsignal` fallback ready as the no-network path. |

---

## 5. What to say about MT5 (Nick will ask "is this really trading?")

Be honest and it lands *better*, not worse:

- **Today's demo runs on the simulator**, which drives the exact same backend, cards,
  and ledger the MT5 EA will. It is clearly labelled "SIMULATOR ONLY — not trading."
- **The MT5 Expert Advisor exists** (`mt5_ea/SignalGateEA.mq5`) and implements polling,
  split-ticket execution, staged TP management, and stop handling. It still needs to be
  compiled and run on a **demo** MetaTrader account and verified — that's the next
  milestone (`docs/CODEX_MT5_COMPILE_AND_TEST.md`), and it will only ever run demo.
- **Never** switch to live. Demo-only is enforced in three places (config, the backend
  command payload's `demo_only`, and the EA's `OnInit` refusal). v1 has no live path.

---

## 6. Hard "do not" list for demo day

- **Do not** set `SIGNAL_EXTRACTOR=fake` and expect real screenshot reading — it returns
  a canned signal.
- **Do not** demo the uncompiled MT5 EA as if it's verified trading. Simulator only.
- **Do not** change `DEMO_ONLY_MODE`. Ever.
- **Do not** claim a track record, verified/reconciled figures, or profitability. The
  honest line is: *"forward-testing on demo; the ledger is the record, and it's being
  built now."* (This is also the marketing plan's core rule — see `docs/MARKETING_DECK.md`.)
- **Do not** paste the real bot token or API key into chat, screen-share it, or commit it.

---

## 7. 60-second reset between run-throughs

If you want a clean slate to demo again (e.g. Nick wants to send a second pair):
```bash
python scripts/reset_local_db.py   # wipes local demo DB
python scripts/init_db.py          # re-create + seed settings
python scripts/seed_settings.py    # (if reset didn't reseed)
```
Then re-register the tester (`/start`) — reset clears users too. For a second *signal*
without a full wipe, just have Nick send another screenshot; each becomes a new `SIG-…`.

---

## 8. Post-demo (optional, if it goes well)

- Export/screenshot the ledger and management-event log — that *is* the "Discipline
  Report" deliverable in the offer ladder (`docs/MARKETING_DECK.md`, Demo Desk tier).
- If Nick wants to keep going, the next real step is the **60–90 day demo forward-test**:
  every Nick signal carded, ledger exported weekly. That accumulated record is the one
  asset that makes the paid tiers honest — see the roadmap slide in the deck.

---

### Quick reference card (print this)

```
BEFORE:  ANTHROPIC_API_KEY real? · SIGNAL_EXTRACTOR=claude? · Nick=provider? ·
         tester /start done (USER id noted)? · /health ok & not paused? ·
         restarted backend+bot after .env edits?

RUN:     1 Backend window   2 Bot window   3 Simulator (on YES)

DEMO:    Nick: 📎 File → screenshot  →  review "Price scale read"  →  Confirm
         Tester: taps YES  →  Ben: run simulator  →  watch FULLY_CLOSED  →  show ledger

SIM:     python simulator/ea_simulator.py --user-id USER-XXXXXX \
              --api-key local-demo-ea-key --backend http://127.0.0.1:8000

FALLBACK: Edit button · /testsignal typed · resend as File · /resume · --scenario stop_out
```
