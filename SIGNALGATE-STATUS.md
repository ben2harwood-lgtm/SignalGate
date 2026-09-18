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
- CI/dependency security: **implemented on integration branch**; dependency resolver/audit gate repaired and green in PR #6 before merge.
- Hosted auth/least privilege: **implemented, PR #2 pending acceptance**.
- Tenant-bound execution/retry safety: **implemented, PR #3 pending acceptance**.
- Adversarial ingestion/parser hardening: **implemented, PR #4 pending acceptance**.
- Provider Edition documentation/site package: **this branch, pending acceptance**.
- Production-operations baseline (readiness/container/backup tooling): **PR #7 pending acceptance**.

## Capability ledger

| Capability | State | Evidence / next gate |
|---|---|---|
| Deterministic signal parsing | Implemented | Existing tests + red-team PR #4 |
| Human YES/NO approval | Implemented | Existing approval tests |
| Demo MT5 execution | Implemented | EA + simulator |
| Ledger/audit trail | Implemented | Existing ledger tests |
| CI + dependency audit | Implemented | GitHub Actions on hardening branch |
| Hosted strong auth | Implemented, unaccepted | PR #2 must pass CI/review |
| Hosted command ownership | Implemented, unaccepted | PR #3 must pass CI/review |
| Retry-safe execution events | Implemented, unaccepted | PR #3 tests |
| Input replay/ambiguity controls | Implemented, unaccepted | PR #4 tests |
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

A branch is not "done" because code exists. It is done only when implementation, automated tests, adversarial tests, review, and acceptance evidence are all present.

No real-money trading should be enabled from this hardening work.
