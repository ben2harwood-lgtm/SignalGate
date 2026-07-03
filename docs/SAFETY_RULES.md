# Safety Rules

These constraints are non-negotiable for v1 and are enforced in code. Each is
listed with where it is enforced.

| # | Rule | Enforced in |
|---|------|-------------|
| 1 | Demo trading only | EA `OnInit` (refuses live), `demo_only` flag on every command |
| 2 | No live account support | EA `IsLiveAccount()` guard; `DemoOnlyMode` default true |
| 3 | No full auto-copy | Every signal requires an explicit YES tap |
| 4 | Raw Telegram text never reaches MT5 | Only structured `CommandOut` JSON is served (`routes/commands.py`) |
| 5 | MT5 gets only validated, approved commands | Commands created only after parse + approval |
| 6 | Every trade opens with a hard SL | Parser requires SL; EA passes SL on every order |
| 7 | One YES → exactly one command | `crud.approve_signal` + `_create_command` |
| 8 | NO → no command | `crud.reject_signal` |
| 9 | Duplicate YES → no duplicate command | unique `(signal_id,user_id)` + existing-approval check |
| 10 | Expired signals → no command | `refresh_signal_expiry` / `_is_expired` |
| 11 | Admin pause blocks command creation | `is_admin_paused` check in `approve_signal` |
| 12 | EA never executes the same command twice | EA `g_processed_ids`; backend marks `SENT_TO_EA` |
| 13 | EA reports success or failure for every command | EA `ReportExecutionSuccess` / `ReportError` |
| 14 | Every partial close, SL move, failure, transition logged | `trade_management_events` + `audit_logs` |
| 15 | No trailing stop | Not implemented; only staged SL moves |
| 16 | No payment system | Not present |
| 17 | No public landing page | Not present |
| 18 | No customer dashboard beyond admin logs | Only `/admin/*` endpoints |
| 19 | No AI parsing | Deterministic `parser.py` only |
| 20 | No extra product features | Scope limited to spec |

## Defence in depth

- **Backend** is the source of truth for idempotency, expiry and pause. Even a
  buggy or malicious EA cannot create or duplicate commands.
- **EA** independently re-validates demo status, symbol, spread and SL/TP
  direction before sending any order, and keeps its own processed-id set.
- **Parser** rejects anything ambiguous (both directions, missing SL/TP,
  inconsistent SL vs TP, bad TP ordering, non-numeric values).

## Honesty

- No profitability is claimed anywhere. The performance ledger records actual
  forward-test outcomes and marks R values **provisional** when entry price is
  unknown. See `PERFORMANCE_LEDGER.md`.
