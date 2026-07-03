# SignalGate — Single Windows VPS Setup (2-week solo test)

Everything runs on ONE Windows VPS: the backend, the Telegram bot, MetaTrader 5,
and the EA. The EA talks to the backend on `127.0.0.1`, so there's no HTTPS,
Postgres, or networking complexity. **Demo account only.**

> Why one box: MetaTrader is Windows-only and must run 24/7; putting the backend
> on the same machine means the EA just uses localhost. Simplest, fewest failure
> points for a solo test.

---

## 0. What you need before starting

- A Windows VPS (Server 2022 or Win 11), ~2 vCPU / 4 GB RAM / 50 GB SSD, admin access.
- The VPS's **public IP**, **username**, and **password** (from your provider).
- `SignalGate_share.zip` (on your Desktop) — or we copy it over during setup.
- Your **Telegram bot token** and your **numeric admin id** (already in your local `.env`).
- Your **Anthropic API key** (for screenshot reading) — or use `SIGNAL_EXTRACTOR=fake` to start.
- Your broker's **demo** login (e.g. FivePercentOnline demo) for MetaTrader.

---

## 1. Connect to the VPS (from your Mac)

1. Install **Microsoft Remote Desktop** from the Mac App Store (free).
2. Add a PC → enter the VPS **public IP** → connect → enter the **username/password**.
3. You're now looking at the Windows desktop. Everything below happens *inside* this
   Remote Desktop window. (This is the window I can drive for you.)

---

## 2. Install Python

1. In the VPS browser, go to **python.org/downloads** and get Python 3.11 or 3.12.
2. Run the installer — **tick "Add Python to PATH"** — then "Install Now".
3. Verify: open **Command Prompt** and run `python --version`.

---

## 3. Copy SignalGate onto the VPS

Easiest options:
- Drag `SignalGate_share.zip` from your Mac into the Remote Desktop window (clipboard
  drag works in Microsoft Remote Desktop), **or**
- In the VPS browser, download it from wherever you keep it (email it to yourself, or a
  cloud drive).

Then **right-click the zip → Extract All** to e.g. `C:\SignalGate`.

---

## 4. Configure `.env`

1. In `C:\SignalGate`, double-click **`Start Backend.bat`**.
2. On first run it creates a `.env` from the template and opens it in Notepad.
3. Fill in and **save**:
   ```env
   TELEGRAM_BOT_TOKEN=your_real_bot_token
   ADMIN_TELEGRAM_IDS=your_numeric_telegram_id
   EA_API_KEY=local-demo-ea-key
   SIGNAL_EXTRACTOR=claude        # or "fake" to start without a key
   ANTHROPIC_API_KEY=sk-ant-...   # leave blank if using fake
   DEMO_ONLY_MODE=true
   REQUIRE_LICENSE=false          # solo test, identify EA by user_id
   ```
   Leave the rest at defaults. `DATABASE_URL` stays SQLite (fine for a solo test).

---

## 5. Start backend + bot

1. Double-click **`Start Backend.bat`** again. It installs dependencies on first run,
   then prints "SignalGate backend is running". **Leave this window open.**
2. Double-click **`Start Bot.bat`**. It prints "SignalGate Telegram bot is running".
   **Leave this window open.**
3. From your phone, message your bot **`/start`** then **`/status`** — status should
   show backend reachable and demo-only. (On the VPS's clean network the bot connects
   without the security-software issues seen on the Mac.)

---

## 6. Install & set up MetaTrader 5

1. In the VPS browser, download MT5 from your broker (or metatrader5.com), install it.
2. Log in to your **demo** account.
3. **Tools → Options → Expert Advisors**: tick **"Allow WebRequest for listed URL"**
   and add: `http://127.0.0.1:8000`
4. Copy `mt5_ea\SignalGateEA.mq5` (from the extracted folder) into MT5's
   `MQL5\Experts` folder (MetaEditor → File → Open Data Folder finds it), then
   **compile** it in MetaEditor (F7).
5. Drag the EA onto a chart (e.g. **BTCUSD** for 24/7 testing, or a forex/gold pair in
   market hours). In the EA inputs leave `BackendURL = http://127.0.0.1:8000`,
   `UserID = USER-000001`, `DemoOnlyMode = true`. Enable **Algo Trading** (toolbar).
6. The EA should print a heartbeat; the backend window logs `EA_HEARTBEAT`.

---

## 7. Prove the loop once

1. Send your bot a **chart screenshot** (or use `/testsignal XAUUSD BUY SL 2343 TP1 2353
   TP2 2358 TP3 2363`).
2. With a screenshot: the bot replies with the extracted entry/SL/TP → tap **Confirm**.
3. The trade card broadcasts → tap **YES**.
4. The EA picks up the command and opens the **demo** trade; you get OPENED, then the
   TP/SL management messages, ending in fully closed.
5. Check `/lastsignals` and `/lastcommands` to see the lifecycle recorded.

If that works end-to-end, you've proven it on the VPS.

---

## 8. Make it survive 24/7 (before you leave)

- **Auto-start on reboot:** press `Win+R`, type `shell:startup`, Enter. Put shortcuts to
  `Start Backend.bat` and `Start Bot.bat` in that Startup folder so they relaunch if the
  VPS reboots. Set MetaTrader to start with Windows (its Options → … or a Startup
  shortcut) and **save the chart with the EA attached** so MT5 re-attaches it.
- **Auto-restart on crash (optional but recommended):** the simplest version is a tiny
  wrapper that relaunches the process if it exits — ask me and I'll add `Start
  Backend (auto-restart).bat` / `Start Bot (auto-restart).bat` that loop on exit.
- **Top up your Anthropic credit** so screenshot reading doesn't stop mid-trip (or run
  `SIGNAL_EXTRACTOR=fake` while away if you only want to exercise the trade loop).
- **Alive check:** from your phone, message the bot `/status` any time — if it replies,
  the bot + backend are up. (Want a daily auto-"I'm alive" ping? I can add a scheduled
  task.)
- **Don't shut down / log off** the VPS — use "Disconnect" in Remote Desktop, which
  leaves everything running. (Logging off can stop MT5/the windows.)

---

## 9. When you get back

- To stop everything: close the backend, bot, and MT5 windows (or turn off Algo Trading).
- If you used an hourly VPS and don't want to keep it: destroy the server in the
  provider dashboard to stop billing.

---

## Reminders

- Demo only. Never log MetaTrader into a live account.
- The bot still needs **you** to tap Confirm and YES for each signal — it does not trade
  on its own, by design.
- Keep your bot token and API key private; they live only in the VPS `.env`.
