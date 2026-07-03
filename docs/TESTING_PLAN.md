# Testing Plan

Automated tests live in `backend/tests/` and run with `pytest`. They use an
isolated temp SQLite database and FastAPI's `TestClient` (no network, no MT5).

```bash
cd backend && source .venv/bin/activate && python -m pytest -q
```

## Coverage

### Parser (`test_parser.py`) — 12 tests
The 10 required cases plus multi-line format and expiry:
1. `XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363` → valid
2. `GOLD BUY SL 2343 TP1 2353 TP2 2358` → valid
3. `XAU SELL SL 2355 TP1 2345 TP2 2340` → valid
4. `BUY XAUUSD TP1 2353` → rejected (missing SL)
5. Random text → rejected
6. Both BUY and SELL → rejected
7. BUY with SL above TP → rejected
8. SELL with SL below TP → rejected
9. BUY with TP2 < TP1 → rejected
10. SELL with TP2 > TP1 → rejected
11. Multi-line `Entry: Market / SL: / TP1:` → valid
12. Expiry timestamp set on valid signal

### Approvals (`test_approvals.py`)
- YES creates exactly one command
- Duplicate YES creates no second command
- NO creates no command
- Reject after approve is blocked (first decision wins)
- Approve after reject is blocked (first decision wins)
- Approving an unregistered user is rejected
- Approving a parser-rejected signal creates no command

### Commands (`test_commands.py`)
- Pending command returned exactly once (then `SENT_TO_EA`, not re-served)
- Pending requires the EA API key (401 otherwise)
- Execution success updates status + records execution
- Execution failure recorded
- Management events update status and are counted

### Expiry (`test_expiry.py`)
- Expired signal cannot be approved
- Expired command not returned to the EA

### Admin pause (`test_admin_pause.py`)
- Pause blocks command creation
- Resume restores approvals
- Admin endpoints require admin header (403 otherwise)

### Ledger (`test_ledger.py`)
- Every signal creates a ledger row
- Parser-rejected signal → ledger `REJECTED`
- User rejection updates ledger
- Command creation updates ledger (`APPROVED_NOT_EXECUTED`)
- Execution + TP events update ledger and compute an approximate R

### Simulator end-to-end (`test_simulator.py`)
- Create → approve → simulator polls → execution + all management events
  recorded → command ends `FULLY_CLOSED`
- Simulator local idempotency (no double processing)

## Manual / MT5 checks (not automated)

- Compile `SignalGateEA.mq5` in MetaEditor (0 errors).
- WebRequest whitelist + demo account guard.
- Live-account refusal (`DEMO_ONLY_VIOLATION`) — verify the EA won't init on a
  real account.
