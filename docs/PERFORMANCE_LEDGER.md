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
- `r_result` — remains `null` without a verified whole-trade realised return. TP targets and stop markers are not return evidence.
- `final_notes` — human-readable milestone context and explicit evidence limitations.

## Why whole-trade realised R is withheld

A `TP1_CLOSE_SUCCESS`, `TP2_CLOSE_SUCCESS`, `TP3_CLOSE_SUCCESS` or
`STOP_LOSS_HIT` event is a **reported milestone**, not a volume-weighted
realised return for the entire position. An event may represent a partial
close, a moved stop, or a residual position with an unknown exit. A target
price alone cannot establish the return on the opening volume.

The ledger preserves those milestones in `result_status` but leaves
`r_result` as `null` for TP, stop, close, or management-failure events.
This is **unknown**, not zero, profit, or loss. Fully closed without an
attributed exit remains `CLOSED_UNATTRIBUTED` for manual review.

## Evidence boundary

This ledger records demo forward-testing events; it is **not** broker P&L,
a verified realised-R calculator, or MT5 demo-broker acceptance. Complete,
broker-confirmed fill and exit sizes, prices, fees and changes to stops are
required before a whole-trade return could be calculated.

Historical non-null `r_result` values written by earlier versions are
legacy target/stop **estimates**, not independently verified performance.
This change does not rewrite historical rows or certify them.
