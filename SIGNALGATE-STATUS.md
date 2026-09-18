# SignalGate — Canonical Status

**As of 18 September 2026.** This file is the single truth for release readiness.

## Product position

SignalGate is being converted from a July demo prototype into **provider-agnostic signal execution infrastructure**.

Commercial proposition:

> **Your signals. Your customers. Your brand. SignalGate provides the controlled path from validated signal to authorised execution, reconciliation and audit.**

SignalGate does **not** supply investment signals and must not make profitability claims.

## Repository truth

- `main`: July demo baseline. Do not market as production SaaS.
- `codex/signalgate-hardening-2026-09-18`: hardening integration branch.
- CI/dependency security: **landed on integration branch**; current integration push CI is green.
- Hosted auth/least privilege: **landed on integration branch via PR #2**; machine-green, still subject to the independent acceptance gate.
- Dependency repair: **landed on integration branch via PR #6**.
- Tenant/account-bound execution and retry safety: **PR #3 machine-green, review-blocked pending migration evidence and independent acceptance**.
- Adversarial ingestion/parser hardening: **PR #4 machine-green, review-blocked pending migration/replay-scope fixes and independent acceptance**.
- Provider Edition documentation/site package: **PR #5 machine-green; copy is explicitly demo-hardening/target-state, pending independent acceptance**.
- Production-operations baseline (readiness/container/backup tooling): **PR #7 machine-green; restore/migration/observability evidence remains open**.
- The repository branch named `claude/signalgate-full-audit-bjh0tk` is a July branch and is **not** an independent review of the 18 September hardening work.

## Current automated evidence

- Hardening integration push at `1ba98e0c59e27bc712f8f05859abd5b99d5e026f`: backend tests, Python compile and dependency audit **passed**.
- PR #3 head `bcc92ddfdbf47d5bfc6a6e7051666317df8a30a5`: CI **passed**.
- PR #4 head `3cec16dc929378414949427e8f55d1cd281e9926`: CI **passed**.
- PR #5 head was machine-green before this status/copy correction; CI must pass again on the corrected head.
- PR #7 head `7dca91efa44fb43a24308d645d36ec6a397db1d6`: backend tests, dependency audits and container build **passed**.

Machine-green is not the same as accepted.

## Cross-review blockers found 18 September

1. **Versioned migrations are mandatory before schema-changing hardening can land.** PR #3 adds an execution uniqueness constraint and a new non-null management-event idempotency column. PR #4 adds signal replay uniqueness. The application currently uses SQLAlchemy `create_all()`, which does not upgrade existing PostgreSQL tables.
2. **Replay identity is not yet multi-provider-safe.** PR #4 keys replay prevention by `(source, source_message_id)`; true provider/feed identity does not exist until G5. A reused message id with different content must fail visibly rather than silently return an older signal.
3. **MetaEditor compilation remains a separate gate.** Linux CI can inspect source invariants but does not prove the modified MQL5 EA compiles with 0 errors/0 warnings.
4. **A current independent Claude PASS/FAIL review is still missing.** The old Claude branch cannot satisfy that requirement.

These are acceptance blockers; they are not reasons to weaken the demo-only work already proven.

## Capability ledger

| Capability | State | Evidence / next gate |
|---|---|---|
| Deterministic signal parsing | Implemented | Existing tests + red-team PR #4 |
| Human YES/NO approval | Implemented | Existing approval tests |
| Demo MT5 execution | Implemented | EA + simulator; recompile modified EA before acceptance |
| Ledger/audit trail | Implemented | Existing ledger tests |
| CI + dependency audit | Implemented | Integration push CI green |
| Hosted strong service auth | Landed, machine-green | Independent acceptance still required |
| Hosted command/account ownership | Implemented on PR #3, unaccepted | Migration + independent review |
| Retry-safe execution events | Implemented on PR #3, unaccepted | Migration + independent review |
| Input replay/ambiguity controls | Implemented on PR #4, unaccepted | Migration + provider-safe replay semantics |
| True provider/organisation multi-tenancy | **Not built** | Release Gate 5 |
| Provider dashboard/onboarding UI | **Not built** | Release Gate 7 |
| Billing/subscription operations | **Not built** | Commercial gate |
| Production observability/SLOs | **Not built** | Release Gate 6 |
| Restore-tested backups/DR | **Not built** | Release Gate 6 |
| Independent penetration test | **Not done** | Release Gate 8 |
| UK regulatory perimeter opinion | **Not done** | Release Gate 8 |
| Provider beta | **Not started** | Release Gate 9 |
| Live retail trading | **Not enabled** | Explicitly blocked pending assurance |

## Non-negotiable truth

A branch is not "done" because code exists. It is done only when implementation, automated tests, adversarial tests, independent review, and acceptance evidence are all present.

No real-money trading should be enabled from this hardening work.
