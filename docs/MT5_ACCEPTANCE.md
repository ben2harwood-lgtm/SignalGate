# MT5 Execution Acceptance Gate

The MQL5 EA is safety-critical and **source-level CI is not a compiler receipt**.

Before this lane can be called release-accepted, compile `mt5_ea/SignalGateEA.mq5` in the target MetaTrader 5 MetaEditor and record:

- frozen candidate ref + exact commit SHA;
- SHA-256 of the exact EA source;
- MetaEditor/build version;
- broker/demo terminal version;
- **0 compile errors**;
- **0 compile warnings**;
- raw compiler log.

## Automated compile receipt harness

Post-RC tooling includes:

- `scripts/capture_mt5_compile_evidence.ps1`
- `scripts/Run-MT5-Compile-Acceptance.bat`

The harness does **not** compile whatever code happens to be checked out. It resolves the frozen release ref, verifies the expected SHA, creates a detached temporary Git worktree at that exact commit, compiles the EA from that worktree, then records/copies:

- candidate ref and SHA;
- detached-worktree HEAD;
- harness/tooling HEAD;
- EA source SHA-256;
- MetaEditor file version;
- MetaTrader terminal file version when discoverable;
- compiler process exit code;
- final MetaEditor error/warning counts;
- exact `.mq5` source;
- raw MetaEditor `.log`;
- JSON and Markdown receipts.

For RC2 on a Windows machine with MetaEditor installed:

```bat
scripts\Run-MT5-Compile-Acceptance.bat ^
  -CandidateRef "release/signalgate-demo-rc2-2026-09-19" ^
  -CandidateSha "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2"
```

If more than one MetaEditor or MQL5 data directory exists, pass `-MetaEditorPath` and `-Mql5Root` explicitly. Ambiguity fails closed rather than guessing.

A PASS receipt requires the MetaEditor log to report exactly **0 errors, 0 warnings**. Evidence is written under `artifacts/mt5-acceptance/`, which is git-ignored because it may contain machine/environment details.

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
