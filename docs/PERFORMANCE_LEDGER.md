# Performance Ledger

The performance ledger (`performance_ledger` table, `backend/app/ledger.py`)
records the honest, full lifecycle of every signal for forward-testing. It
makes **no profitability claims** and never fabricates results.

## One row per signal

A ledger row is created for **every** signal at creation time — valid or
rejected. It is updated as the signal moves through its lifecycle.

## `result_status` lifecycle

```
PENDING                (valid signal, no decision yet)
  → REJECTED           (parser rejected, or user tapped NO)
  → APPROVED_NOT_EXECUTED   (command created, awaiting EA)
  → EXECUTED_OPEN      (EA opened the demo position)
  → TP1_HIT / TP2_HIT / TP3_HIT   (take-profit stages reached)
  → STOPPED_OUT        (stop loss hit)
  → BREAKEVEN          (closed at breakeven after SL move)
  → FAILED             (execution or management failure)
  → EXPIRED            (signal/command expired before execution)
```

## Updated on

signal creation, approval, rejection, command creation, execution
success/failure, TP1/TP2/TP3 events, stop-loss hit, full close, and failures.

## Fields of note

- `signal_to_card_delay` — seconds from signal creation to command creation.
- `approval_to_execution_delay` — seconds from command creation to execution.
- `slippage`, `spread_at_execution` — captured from the EA execution report.
- `r_result` — **approximate** R multiple (reward ÷ risk).
- `final_notes` — human-readable context, including "R provisional" warnings.

## Approximate R calculation

```
BUY:   risk = entry_price - initial_stop_loss
       reward(TP) = tp_price - entry_price
SELL:  risk = initial_stop_loss - entry_price
       reward(TP) = entry_price - tp_price
R(TP) = reward(TP) / risk        (only when risk > 0)
```

If the executed entry price is not reported, the signal's entry/market
placeholder is used and `final_notes` records that **R is provisional**. A
stop-out is recorded conservatively as approximately **−1R** (or breakeven if
the SL had already been moved up).

## Why approximate

This is a local forward-testing tool, not a P&L accounting system. R is a
risk-normalised sanity check on signal quality, deliberately conservative.
Real broker statements remain the authority for any actual account.
