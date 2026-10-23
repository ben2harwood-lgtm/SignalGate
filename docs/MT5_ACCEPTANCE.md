# MT5 Execution Acceptance Gate

The MQL5 EA is safety-critical and **source-level CI is not a compiler receipt**.

**Frozen RC2 is NOT a valid broker-demo onboarding candidate.** The exact RC2
release SHA `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2` failed official
MetaEditor compilation with **18 errors / 4 warnings** (workflow run
`35464044898`; see issue #46). A later repaired EA compiled at a *different*
SHA; it does not turn RC2 into a compiler PASS. Keep RC2 immutable. Before
collecting *new* broker-demo acceptance evidence, pin a separately reviewed
replacement candidate, obtain its own exact-source **0 errors / 0 warnings**
MetaEditor receipt, and satisfy the demo-broker scenarios below. PR #60's
execution-attribution HOLD remains open as of 23 October 2026.

Before this lane can be called release-accepted, compile `mt5_ea/SignalGateEA.mq5` in the target MetaTrader 5 MetaEditor and record:

- named candidate ref + exact commit SHA;
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

The harness does **not** compile whatever code happens to be checked out. It resolves the named candidate ref, verifies the expected SHA, creates a detached temporary Git worktree at that exact commit, compiles the EA from that worktree, then records/copies:

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

Historical RC2 *failure reproduction only* on a Windows machine with MetaEditor
installed (do **not** use this command as a passing acceptance candidate):

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
   TP1/TP2/TP3 stage receipts require the **specific child position/deal's** broker
   TP-exit reason, not just a reduced open-position count or an earlier child's TP.
   A partial manual/unknown close, or manual final close after an earlier TP,
   must not falsely advance a TP stage; broker-mutated identifiers/comments
   must fail closed pending reconciliation;
7. netting account — split-ticket mode falls back safely;
8. network interruption after broker fill — open-position reconciliation recovers the missing callback;
9. EA restart with an open SignalGate position — reconciliation runs and new command polling remains blocked until flat;
10. conflicting broker snapshot — backend returns conflict and does not rewrite execution history.

## Current automated evidence

Linux CI asserts the source contains the fail-closed invariants above and backend tests exercise execution state gating, reconciliation recovery, conflict handling and licence ownership.

## Release rule

No real-money mode is enabled by this gate. Until the actual MetaEditor compile + demo scenario receipts are attached to the release evidence, MT5 execution remains **machine-tested but not externally accepted**.

## Broker-free candidate rehearsal

Before arranging a demo-account operator session, run:

```bash
python scripts/run_broker_free_rehearsal.py \
  --candidate-sha <full-40-character-commit-sha> \
  --output /private/path/new-rehearsal-receipt
```

Use a Python environment with the backend requirements installed. The output
folder must not already exist. The tool extracts the exact committed candidate
into a temporary directory and runs named API/simulator and static-source checks
against an isolated temporary SQLite database. Local uncommitted source is not
used. It writes a timestamped JSON receipt, JUnit results, test log and artifact
hashes, bound to the candidate SHA and EA-source hash. It also checks that the
archived candidate files are unchanged after the tests, and hashes the exact
JUnit bytes it validates. Every expected test must
actually pass; skipped or missing scenarios cannot yield a rehearsal PASS.

The ten scenario rows explicitly distinguish **synthetic API evidence** from
**source-only checks**. The tenant API rehearsal obtains subscriber consent,
claims an authorised command, omits a fabricated execution callback, recovers
from a fabricated position snapshot, rejects a conflicting snapshot, and proves
an unattributed manual close plus retry is exported once without an invented TP
return or cross-tenant data.

This tool does not launch MetaTrader, connect to a broker or place any orders.
A `REHEARSAL_PASS` leaves **actual MT5 demo acceptance OPEN** and every real-broker
scenario `NOT_RUN`. Suffix handling, LIMIT refusal, netting behaviour and restart
poll blocking still require the exact EA in an authorised, positively identified
demo terminal. Retain actual broker/terminal receipts separately; do not relabel a
synthetic snapshot or source assertion as broker evidence.
