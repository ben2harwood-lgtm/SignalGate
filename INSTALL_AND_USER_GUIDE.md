# SignalGate — Complete Install & User Guide

**A Telegram → MetaTrader 5 demo trade execution system.**
This guide is written so that someone who has *never touched code* can get the whole thing running on a fresh computer. Follow it top to bottom. Don't skip steps.

---

## 0. Read this first (the 60-second summary)

SignalGate does this:

1. An admin types a trade signal into Telegram (e.g. `XAUUSD BUY SL ... TP1 ...`).
2. A bot turns it into a tidy **trade card** with **YES / NO** buttons.
3. When you tap **YES**, a backend creates **one** safe, structured trade command.
4. An **Expert Advisor (EA)** running inside MetaTrader 5 picks up that command and places a **demo trade**, then manages take-profits and stop-loss and reports everything back.

There are **four programs** that make this work:

| Piece | What it is | Where it runs |
|---|---|---|
| **Backend** | The brain. A small web server (Python/FastAPI) + database. | Your computer |
| **Telegram bot** | The chat interface (Python). | Your computer |
| **EA** (`SignalGateEA.mq5`) | The thing that actually trades. | Inside MetaTrader 5 |
| **Simulator** | A fake EA for testing without MetaTrader. | Your computer |

> ### ⚠️ SAFETY — READ THIS
> - **This is DEMO ONLY.** It is built to refuse live accounts. Keep it that way.
> - **Only ever attach the EA to a broker DEMO account.**
> - It places tiny test trades (0.01–0.04 lots). It is for *forward-testing*, not for making money. There are **no profit claims**, anywhere.
> - Never put real money behind v1.

---

## 1. What you need before you start (shopping list)

Tick all of these off **before** you begin:

- [ ] **A computer** — Mac or Windows.
- [ ] **Python 3.10 or newer** installed (see Part 2).
- [ ] **A Telegram account** (the phone app or desktop app).
- [ ] **A MetaTrader 5 DEMO account** from any broker (free to open).
- [ ] **MetaTrader 5 installed.**
  - On **Windows**: install MT5 directly.
  - On **Mac**: MT5 only runs properly inside **Parallels Desktop** (a Windows virtual machine). This adds one networking step — covered in Part 7. The plain "MT5 for Mac" build often cannot run Expert Advisors reliably, which is why Parallels is recommended.
- [ ] **The SignalGate project files** (the `SignalGate.zip` that came with this guide).
- [ ] About **45 minutes** and a bit of patience the first time.

You do **not** need to be a programmer. You will copy-paste a few commands.

---

## 2. Install Python (one time)

### Windows
1. Go to https://www.python.org/downloads/ and download the latest Python 3.
2. Run the installer. **Important:** on the first screen, tick **"Add Python to PATH"**, then click *Install Now*.
3. To check it worked: open **Command Prompt** (press Start, type `cmd`, Enter) and type:
   ```
   python --version
   ```
   You should see something like `Python 3.12.x`.

### Mac
1. Macs come with an old Python. Install a current one with [Homebrew](https://brew.sh) or from python.org.
2. Check it in **Terminal** (press Cmd+Space, type `Terminal`, Enter):
   ```
   python3 --version
   ```
   You should see `Python 3.10` or higher.

> Throughout this guide, where you see `python`, Mac users may need to type `python3` instead.

---

## 3. Unzip the project

1. Unzip `SignalGate.zip`. You'll get a folder called `signalgate`.
2. Put it somewhere easy, e.g. your **Desktop**. So the path is:
   - Windows: `C:\Users\<you>\Desktop\signalgate`
   - Mac: `~/Desktop/signalgate`
3. Inside you should see folders: `backend`, `telegram_bot`, `mt5_ea`, `simulator`, `scripts`, `docs`, and files `.env.example`, `README.md`.

> Everywhere below, "the project folder" means this `signalgate` folder.

---

## 4. Create your Telegram bot (get your token)

**Every person needs their own bot. Do not reuse someone else's token.**

1. Open Telegram. In the search bar, type **@BotFather** and open the one with the blue ✓ verified tick.
2. Send the message: `/newbot`
3. It asks for a **name** (anything, e.g. `My SignalGate Bot`).
4. It asks for a **username** — must be unique and **end in `bot`** (e.g. `my_signalgate_demo_bot`).
5. BotFather replies with a line like:
   ```
   Use this token to access the HTTP API:
   1234567890:AAH...your-secret-token...
   ```
   **Copy that whole token.** Keep it secret — anyone with it controls your bot.

> **Tip:** In Telegram, you can *click* the token text once and it copies itself to your clipboard.

---

## 5. Get your numeric Telegram ID (your "admin ID")

The system needs to know which Telegram user is the admin. That's a number, not your @username.

The easy way (after the backend + bot are running in Parts 6–8): just send your bot `/status` and it replies with `telegram id 123456789`. That number is your admin ID.

For now, just know you'll need it. If you want it early, message the bot **@userinfobot** and it replies with your ID — but use the official one and don't share the number publicly.

---

## 6. Configure the project (the `.env` file)

1. In the project folder there is a file called **`.env.example`**. Make a **copy** of it and rename the copy to exactly **`.env`** (no `.example`, and yes it starts with a dot).
   - Windows tip: if you can't see the file extension, turn on "File name extensions" in File Explorer's View menu.
2. Open `.env` in any text editor (Notepad / TextEdit in plain-text mode).
3. Fill in these three lines:
   ```env
   TELEGRAM_BOT_TOKEN=paste-your-token-from-BotFather-here
   ADMIN_TELEGRAM_IDS=your-numeric-telegram-id
   EA_API_KEY=local-demo-ea-key
   ```
   - `TELEGRAM_BOT_TOKEN` — the token from Part 4. **No quotes.**
   - `ADMIN_TELEGRAM_IDS` — your number from Part 5. (You can add more, comma-separated.)
   - `EA_API_KEY` — any password-like phrase. It just has to **match** the EA later. The default is fine.
4. Leave everything else as-is. Save the file.

> **Golden rule:** every time you change `.env`, you must **restart** the backend and the bot for the change to take effect (Parts 7–8). They only read `.env` once, at startup.

---

## 7. Start the Backend (Terminal window #1)

You'll keep this window open the whole time it's running.

Open a terminal (Windows: `cmd`; Mac: `Terminal`) and run these **one line at a time**:

```bash
cd ~/Desktop/signalgate/backend          # Mac
# or on Windows:  cd %USERPROFILE%\Desktop\signalgate\backend

python -m venv .venv                      # makes a private Python environment (first time only)
```

Activate it:
- **Mac:** `source .venv/bin/activate`
- **Windows:** `.venv\Scripts\activate`

Then:
```bash
pip install -r requirements.txt           # installs dependencies (first time only)
python ../scripts/init_db.py              # creates the database + default settings
```

Now start it. **Pick the right command for your setup:**

- **If MetaTrader runs on the SAME computer as the backend** (e.g. all on one Windows PC):
  ```bash
  uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
  ```
- **If MetaTrader runs in Parallels (Mac) or on a DIFFERENT computer** — you MUST bind to all interfaces or the VM/other PC can't reach it:
  ```bash
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```

You're good when you see:
```
INFO: Application startup complete.
INFO: Uvicorn running on http://...:8000
```

**Quick check:** open a browser and go to `http://127.0.0.1:8000/health`. You should see:
```json
{"status":"ok","demo_only_mode":true,"admin_paused":false}
```

> Leave this window running. To stop the backend later, click it and press **Ctrl+C**.

---

## 8. Start the Telegram bot (Terminal window #2)

Open a **second** terminal window (don't close the first):

```bash
cd ~/Desktop/signalgate/telegram_bot      # Mac (Windows: cd %USERPROFILE%\Desktop\signalgate\telegram_bot)
python -m venv .venv
```
Activate it (Mac: `source .venv/bin/activate` · Windows: `.venv\Scripts\activate`), then:
```bash
pip install -r requirements.txt
python run_bot.py
```

It will sit there printing `getUpdates ... 200 OK` lines. That means it's alive.

Now in Telegram:
1. Open your bot (search its username).
2. Send `/start` — it replies "SignalGate demo tester registered."
3. Send `/status` — it shows your `telegram id`. **If that number isn't already in your `.env` `ADMIN_TELEGRAM_IDS`, add it now, then restart BOTH the backend and the bot** (Ctrl+C in each window, run the start commands again). Admin commands won't work until your ID is loaded.

---

## 9. Test the WHOLE chain WITHOUT MetaTrader (do this first!)

This proves Telegram → backend → "EA" works before you fight with MetaTrader. It uses the built-in **simulator** (a fake EA — it does **not** place real trades).

Open a **third** terminal:
```bash
cd ~/Desktop/signalgate
source backend/.venv/bin/activate          # Mac (Windows: backend\.venv\Scripts\activate)
python simulator/run_demo_flow.py --admin-id <YOUR_ADMIN_ID> --api-key local-demo-ea-key
```
Replace `<YOUR_ADMIN_ID>` with your number from Part 8.

You should see it march through: register → signal → approve → OPEN → TP1 → breakeven → TP2 → TP1 → TP3 → **FULLY_CLOSED**. If you see that, **the core system works.** 🎉

> Don't move to MetaTrader until this passes. Otherwise you'll be debugging four things at once.

---

## 10. Set up MetaTrader 5 (the EA)

### 10.1 The networking step (the #1 thing people get wrong)

The EA talks to your backend over the network. **The address the EA uses depends on where MT5 runs:**

| Your setup | EA `BackendURL` should be | Backend must be started with |
|---|---|---|
| MT5 on the **same** Windows PC as the backend | `http://127.0.0.1:8000` | `--host 127.0.0.1` (or `0.0.0.0`) |
| MT5 in **Parallels on a Mac**, backend on the Mac | `http://10.211.55.2:8000` (Parallels' "host" address — see note) | `--host 0.0.0.0` |
| MT5 on a **different computer** on your network | `http://<the-backend-computer's-LAN-IP>:8000` | `--host 0.0.0.0` |

**Why?** Inside a Parallels Windows VM, `127.0.0.1` means *Windows itself*, not your Mac. Parallels exposes the Mac to the VM at a special address — usually **`10.211.55.2`** in the default "Shared Network" mode.

**How to find the right address (do this — don't guess):** open a browser **inside Windows/MT5's machine** and visit `http://10.211.55.2:8000/health` (Parallels) or `http://<LAN-IP>:8000/health`. If you see the `{"status":"ok"...}` JSON, that's your address. To find your Mac's LAN IP, run `ipconfig getifaddr en0` in the Mac Terminal.

### 10.2 Install and compile the EA

1. In MetaTrader 5: **File → Open Data Folder**. A file window opens.
2. Go into **`MQL5` → `Experts`**.
3. Copy **`SignalGateEA.mq5`** (from the project's `mt5_ea` folder) into that `Experts` folder.
   - On Mac/Parallels, your Mac files appear in Windows under **"This PC → Home on 'Mac' (Z:)"**.
4. Double-click `SignalGateEA.mq5` — it opens in **MetaEditor**.
5. Click **Compile** (or press **F7**). You want **"0 errors, 0 warnings"**. A `SignalGateEA.ex5` is created.

### 10.3 Allow the EA to reach the backend (WebRequest whitelist)

MT5 blocks outbound web calls by default.
1. In MT5: **Tools → Options → Expert Advisors** tab.
2. Tick **"Allow algorithmic trading."**
3. Tick **"Allow WebRequest for listed URL."**
4. In the box, add your exact backend URL from the table in 10.1 (e.g. `http://10.211.55.2:8000`). Press Enter so it appears in the list.
5. Click **OK**.

Also make sure the **Algo Trading** button in the top toolbar is enabled (green).

### 10.4 Attach the EA to a chart

1. **Log into a broker DEMO account** in MT5. (The EA refuses live accounts on purpose.)
2. Open a chart for the symbol you want to test (e.g. **XAUUSD**, or **BTCUSD** on weekends — see Part 11).
3. In the **Navigator** (left side) → **Expert Advisors** → drag **SignalGateEA** onto the chart (or double-click it).
4. In the dialog:
   - **Common tab:** tick **"Allow Algo Trading."**
   - **Inputs tab:** set these:
     | Input | Value |
     |---|---|
     | `BackendURL` | your URL from 10.1 (e.g. `http://10.211.55.2:8000`) |
     | `UserID` | **your** backend user id — see note below |
     | `EAApiKey` | must match `EA_API_KEY` in `.env` (default `local-demo-ea-key`) |
     | `DemoOnlyMode` | `true` (leave it) |
     | `SplitTicketDemoPartialMode` | `false` for the smallest first test (one 0.01 trade); `true` to demo the full TP1/TP2/TP3 lifecycle (~0.04 lots) |
     | `MaxSpreadPoints` | `500` is fine for forex/gold; raise to `10000` for crypto (BTC has a wide spread) |
5. Click **OK**. A 😊 smiley in the top-right of the chart = EA running.

> **What is `UserID`?** When you `/start` the bot, the backend gives your Telegram account an id like `USER-000001`, `USER-000002`, etc. The EA only fetches commands for the `UserID` you type here, and a command is created for **whoever taps YES**. So `UserID` must match the account that will tap YES. If you're the only tester and the first to register, you're `USER-000001`. If unsure, the admin command `/users` shows how many exist; the very first registered user is `USER-000001`, the next `USER-000002`, and so on.

### 10.5 Confirm the EA connected

In MT5, open the **Toolbox** (bottom) → **Experts** tab. You should see:
```
SignalGateEA starting. DEMO ONLY. No live trading.
```
No `DEMO_ONLY_VIOLATION` and no `WebRequest` error = you're connected. (If you see `DEMO_ONLY_VIOLATION`, the account is not a demo — switch to a demo account.)

---

## 11. Run a real demo trade (the moment of truth)

1. In Telegram, as the admin, send a signal. **Use prices near the symbol's current price**, or the EA will (correctly) reject it.
   - Gold example (when gold ≈ 2350): `/testsignal XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363`
   - Bitcoin example (when BTC ≈ 60,000): `/testsignal BTCUSD BUY SL 59000 TP1 62000 TP2 63000 TP3 64000`
2. A **trade card** appears with **YES / NO**.
3. Tap **✅ YES: Place Demo Trade**.
4. Within a couple of seconds the EA grabs the command and places the demo trade. Watch:
   - the **Trade** tab in MT5 (a position appears),
   - the **Experts** tab (log lines),
   - **Telegram** (you get "Demo trade OPENED…" and TP/SL updates).

### ⏰ Weekend / market-hours note (important!)
- **Forex and gold (XAUUSD) are CLOSED on weekends.** If you test then, the order is rejected with **`retcode 10018` (market closed)** — that's normal, not a bug. You'll still see the whole pipeline work; only the fill is blocked.
- **Crypto (BTCUSD, ETHUSD…) trades 24/7**, including weekends — perfect for weekend testing. Set the EA's `MaxSpreadPoints` to `10000` first, because crypto spreads are wide.

---

## 12. Bot command reference

| Command | Who | What it does |
|---|---|---|
| `/start` | anyone | Registers you as a demo tester. |
| `/status` | anyone | Shows your Telegram id, backend health, demo mode, paused status. |
| `/settings` | anyone | Shows the current demo settings. |
| `/testsignal <signal>` | admin | Parses a signal and sends a trade card to testers. |
| `/pause` | admin | Blocks all new commands (kill-switch). |
| `/resume` | admin | Un-pauses. |
| `/users` | admin | Shows how many active users exist. |
| `/lastsignals` | admin | Recent signals. |
| `/lastcommands` | admin | Recent commands + counts. |

Signal format the parser accepts (single line or multi-line):
```
XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363
```
Aliases: `GOLD`/`XAU` → `XAUUSD`; `BTC` → `BTCUSD`; `ETH` → `ETHUSD`; `LONG`=BUY, `SHORT`=SELL.
Rules it enforces (or it rejects the signal): one symbol, one direction, a stop loss, at least TP1, and sane ordering (BUY: SL below, TP1<TP2<TP3; SELL: the reverse).

---

## 13. Common mistakes (and how to fix them)

**"The bot doesn't reply at all."**
→ The bot program isn't running, or the token is wrong. Check Terminal #2 is open and printing `200 OK`. Re-check `TELEGRAM_BOT_TOKEN` in `.env` (no quotes, no spaces), then restart the bot.

**"Admin commands say I'm not allowed."**
→ Your numeric ID isn't in `ADMIN_TELEGRAM_IDS`, **or** you edited `.env` but didn't restart. Run `/status`, copy the id, put it in `.env`, restart **both** backend and bot.

**"`/testsignal` worked once, but nothing reaches MetaTrader."**
→ Almost always the **networking** (Part 10.1). Test `http://<your-url>/health` *from inside the MT5 machine's browser*. If it fails: backend wasn't started with `--host 0.0.0.0`, or you used `127.0.0.1` inside a VM, or the URL isn't whitelisted in MT5.

**"EA log shows a WebRequest error."**
→ You didn't add the **exact** URL to **Tools → Options → Expert Advisors → Allow WebRequest for listed URL**. It must match `BackendURL` character-for-character (including `http://` and the port).

**"Order rejected: retcode 10018."**
→ Market is **closed** (weekend / outside session). Test crypto instead, or wait for the session to open.

**"EA reports SPREAD_TOO_HIGH."**
→ The spread is above `MaxSpreadPoints`. Raise it (crypto needs ~`10000`).

**"EA reports DEMO_ONLY_VIOLATION and won't trade."**
→ Good — that's the safety guard. You're on a non-demo account. Switch MT5 to a **demo** account.

**"EA reports INVALID_STOP_LOSS / INVALID_TAKE_PROFIT."**
→ Your signal's prices don't make sense versus the **current** price (e.g. a BUY with take-profits below the market). Use levels near the live price.

**"SYMBOL_NOT_FOUND."**
→ The broker's symbol name differs (e.g. `XAUUSD.pro`, `BTCUSD.m`). Either add the symbol to **Market Watch** (right-click → Symbols), or set the EA's `SymbolOverride` to the exact broker name. Also: the parser only knows the symbols in its alias list — to add a new instrument, add it to `SYMBOL_ALIASES` in `backend/app/parser.py`.

**"Duplicate YES made two trades."**
→ It won't. A second YES returns "Already approved" and creates no second command — by design.

**"I changed `.env` and nothing happened."**
→ Restart the backend and bot. They read `.env` only at startup.

**"Pip install failed on Mac."**
→ Use `python3`/`pip3`, and make sure you **activated** the `.venv` first (your prompt should show `(.venv)`).

---

## 14. FAQ

**Q: Is this safe? Can it lose real money?**
A: It is demo-only by design and refuses live accounts. Keep `DemoOnlyMode = true` and only attach to a broker **demo** account. It is for forward-testing, not profit.

**Q: Does my Telegram message get sent straight to MetaTrader?**
A: No. Raw text never reaches MT5. It's parsed into a strict, validated structure first; MT5 only ever receives a clean, approved command. That's a core safety boundary.

**Q: Why does it open 3 trades (0.04 lots) instead of one?**
A: That's "split-ticket" mode. A single 0.01 lot can't be partially closed 50/25/25 (that needs 0.005 lots, below the minimum). So to demo partial profit-taking it opens three child positions (0.02 + 0.01 + 0.01). Set `SplitTicketDemoPartialMode = false` for a single 0.01 trade.

**Q: Do I need to keep the terminal windows open?**
A: Yes. The backend and bot run **in** those windows. Closing them stops the system. (For always-on, you'd later run them as background services — not needed for testing.)

**Q: Can two people use it?**
A: Yes — each person sends `/start` to register, and each gets their own `USER-00000X` id. Each EA instance polls one `UserID`.

**Q: It worked on weekdays but not weekends.**
A: Forex/gold markets close on weekends (`retcode 10018`). Use crypto (BTCUSD) for weekend tests.

**Q: How do I move money / go live?**
A: You don't, in v1. There is deliberately no live trading, no payments, and no auto-copying. Those are out of scope for safety.

**Q: Where's the data / logs?**
A: In `backend/signalgate.db` (a SQLite file) and the audit/ledger tables. Admin endpoints and `/lastcommands` summarise it.

---

## 15. How to stop everything

- In each terminal window (backend, bot, simulator): click it and press **Ctrl+C**.
- In MT5: turn off **Algo Trading**, or right-click the chart → **Expert Advisors → Remove**.
- Your data stays in `backend/signalgate.db`. To wipe and start fresh: `python scripts/reset_local_db.py` (local only).

---

## 16. Quick start (for when you've done it once)

```
# Terminal 1 – backend
cd signalgate/backend && source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 – bot
cd signalgate/telegram_bot && source .venv/bin/activate
python run_bot.py

# In MT5: confirm Algo Trading is on and the EA smiley is showing.
# In Telegram: /testsignal BTCUSD BUY SL 59000 TP1 62000 TP2 63000 TP3 64000  → tap YES
```

---

*Built as a local demo prototype. Demo only. No profit claims. No live trading in v1.*
