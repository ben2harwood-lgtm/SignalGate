# Demo Script

A 16-step walkthrough of the full demo lifecycle. Assumes `.env` is set and
dependencies installed (see `LOCAL_SETUP.md`).

## Setup

1. **Start the backend.**
   ```bash
   cd backend && source .venv/bin/activate
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
2. **Start the Telegram bot.**
   ```bash
   cd telegram_bot && source .venv/bin/activate && python run_bot.py
   ```
3. **Register the tester:** in Telegram send `/start`.
   → "SignalGate demo tester registered. Demo mode only. No live trades."

## Run

4. **Admin sends a signal:**
   ```
   /testsignal XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363
   ```
5. **User receives the trade card** with YES/NO buttons.
6. **User presses YES.**
   → "Approved. Waiting for MetaTrader EA to execute demo trade."
7. **Backend creates exactly one command** (status `PENDING`).
8. **Simulator (or EA) receives the command** by polling `/commands/pending`.
   - Start the simulator if not running:
     ```bash
     python simulator/ea_simulator.py --user-id USER-000001 --api-key local-demo-ea-key
     ```
9. **Execution is reported** → command `EXECUTED_OPEN`. Telegram: "Demo trade
   OPENED…".
10. **TP1 event** reported → `PARTIAL_TP1_DONE`.
11. **SL move to breakeven** reported.
12. **TP2 event** reported → `PARTIAL_TP2_DONE`.
13. **SL move to TP1** reported.
14. **TP3 event** reported.
15. **FULLY_CLOSED** reported → command `FULLY_CLOSED`.
16. **Admin checks logs and ledger:**
    ```
    /lastsignals
    /lastcommands
    ```
    or `GET /admin/status` with header `X-Admin-Id: <your id>`.

## One-command alternative

To run steps 4–15 without Telegram:

```bash
python simulator/run_demo_flow.py --admin-id <YOUR_ADMIN_ID> --api-key local-demo-ea-key
```

## Safety checks to demo

- **Duplicate YES**: tap YES twice → second reply says "Already approved. No
  duplicate command created." Still only one command exists.
- **Expired signal**: wait past `DEFAULT_SIGNAL_EXPIRY_MINUTES`, then YES →
  "Signal expired. No command created."
- **Admin pause**: `/pause`, then YES → "Trading paused. No command created."
  `/resume` restores normal behaviour.
- **Bad signal**: `/testsignal random text` → parser rejects with a reason; no
  card is sent.
