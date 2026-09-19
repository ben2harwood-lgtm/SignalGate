# MT5 Execution Acceptance Gate

The MQL5 EA is safety-critical and **source-level CI is not a compiler receipt**.

Before this lane can be called release-accepted, compile `mt5_ea/SignalGateEA.mq5` in the target MetaTrader 5 MetaEditor and record:

- MetaEditor/build version;
- broker/demo terminal version;
- EA commit SHA;
- **0 compile errors**;
- **0 compile warnings**;
- screenshot or exported compiler log.

Then run these demo-account scenarios and retain backend audit/ledger receipts:

1. normal MARKET fill;
2. broker symbol with suffix (for example `EURUSD.a`);
3. LIMIT command refusal — no broker order;
4. broker rejection / market closed — no fake successful execution;
5. stop-loss close — ledger records `STOPPED_OUT`, never TP;
6. manual/unknown close — ledger remains unattributed unless broker TP/SL reason proves otherwise;
7. netting account — split-ticket mode falls back safely;
8. network interruption after broker fill — open-position reconciliation recovers the missing callback;
9. EA restart with an open SignalGate position — reconciliation runs and new command polling remains blocked until flat;
10. conflicting broker snapshot — backend returns conflict and does not rewrite execution history.

## Current automated evidence

Linux CI asserts the source contains the fail-closed invariants above and backend tests exercise execution state gating, reconciliation recovery, conflict handling and licence ownership.

## Release rule

No real-money mode is enabled by this gate. Until the actual MetaEditor compile + demo scenario receipts are attached to the release evidence, MT5 execution remains **machine-tested but not externally accepted**.
