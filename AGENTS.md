# SignalGate — Agent Instructions

These instructions are authoritative for AI/code agents working in this repository.

## Current product state

SignalGate is **provider-agnostic, tenant-scoped, human-authorised signal-execution infrastructure**. It is not the July local prototype anymore.

The current operating mode remains **demo-only**.

Canonical truth:

1. `SIGNALGATE-STATUS.md`
2. `docs/RELEASE_CANDIDATE_2026-09-19.md`
3. `docs/TESTING_PLAN.md`
4. `docs/EXTERNAL_ACCEPTANCE_HANDOFF.md`
5. `README.md`

Frozen demo RC:

`release/signalgate-demo-rc-2026-09-19`

Do not modify that frozen branch to “tidy up” acceptance work. Runtime/source changes require a new candidate and new evidence as appropriate.

## Non-negotiable safety invariants

1. Demo accounts only unless a later, explicitly authorised release changes the operating mode.
2. Explicit subscriber authorisation remains required per transaction.
3. Raw Telegram/screenshot text never reaches MT5 as execution authority.
4. Provider/feed/subscriber/trading-account ownership is tenant scoped.
5. Cross-tenant reads, writes, broadcasts and execution are unacceptable.
6. Provider identity requires real authentication; an id/header alone is not authority.
7. Customer EA licences and provider credentials remain secret/hashed according to the current design.
8. Providers cannot silently attach subscribers. Subscriber feed membership comes from explicit one-time invite acceptance.
9. Hosted provider Telegram sources use feed-bound source binding; do not restore the old shared `/provider <code>` model.
10. Duplicate decisions/callbacks/retries must not produce duplicate execution state.
11. Broker reconciliation is authoritative after ambiguous network outcomes; never blind-resend after a possible broker fill.
12. Reconciliation conflicts fail closed.
13. Real-account attempts remain refused by the demo EA.
14. Safety-critical and tenant changes require negative/adversarial tests.
15. No profitability claims.

## Current architecture

The active Provider Edition includes:

- organisation/provider/feed/subscriber/trading-account tenancy;
- provider-specific hashed credentials and rotation;
- one-time hashed customer EA licences;
- one-time subscriber consent invites;
- feed policy and provider/feed pause controls;
- tenant-bound Telegram provider-source bindings;
- deterministic fail-closed signal parser;
- structured trade cards and explicit YES/NO;
- retry-safe command/execution/management lifecycle;
- broker-truth MT5 handling and reconciliation;
- Provider Portal, branding/configuration and demo bootstrap;
- provider history/reconciliation and tenant-scoped evidence export;
- tamper-evident audit hash chain;
- PostgreSQL/Alembic hosted schema;
- structured request logs/protected operational metrics;
- encrypted backup/restore baseline;
- provider pilot/assurance documentation.

Do not re-implement these as “future work” because an old file says they are missing.

## Legacy patterns that are NOT current Provider Edition

Do not introduce or restore:

- shared `SIGNAL_PROVIDER_INVITE_CODE` as hosted provider authentication;
- `/provider <shared-code>` as the current provider onboarding flow;
- provider direct subscriber attachment without subscriber consent;
- guessed sequential `USER-000001` identities as an onboarding mechanism;
- plaintext customer/provider credentials;
- SQLite/local-demo identity shortcuts in hosted mode;
- admin-only signal creation as the product model;
- automatic copy execution without per-transaction user action;
- blind retry after uncertain broker execution.

Historical documents may describe these patterns. Canonical status/current runbooks win.

## Change discipline

Before changing code:

1. Identify the canonical integration base.
2. Read the relevant current tests/docs.
3. Keep the frozen RC unchanged unless the task explicitly creates a new release candidate.
4. Work on a dedicated branch/PR.
5. Prefer the smallest change that closes a verified gap.

For schema changes:

- add/review an Alembic migration;
- test upgrade/check/downgrade/re-upgrade on PostgreSQL;
- preserve hosted fail-closed schema checks.

For provider-scoped changes:

- add/retain cross-tenant negative tests;
- test wrong/revoked credentials;
- check logs/exports for secret/privacy leakage.

For execution changes:

- preserve idempotency;
- preserve owner/account binding;
- test retries, terminal-state regression and reconciliation conflicts;
- do not claim MT5 acceptance without the actual MetaEditor/demo receipt.

## Required machine proof

The integration CI matrix is the minimum:

- full backend tests on SQLite;
- full backend tests on PostgreSQL;
- Python compile checks;
- Bandit medium/high scan;
- dependency audits;
- Alembic/PostgreSQL migration smoke;
- hosted container build;
- encrypted backup + isolated restore smoke.

Machine-green is necessary, not sufficient for production/external acceptance.

## External gates agents must not invent

Do not mark these complete without real receipts:

- MetaEditor 0-error / 0-warning compile;
- MT5 demo scenario acceptance;
- independent security review/pentest;
- UK regulatory/financial-promotion advice;
- privacy/contract review;
- deployed central telemetry/alerting and measured SLO history;
- production-like recovery drill;
- real-provider controlled pilot evidence;
- paying-customer/commercial operating evidence.

Use `docs/ACCEPTANCE_EVIDENCE_INDEX.md` and `docs/evidence/` templates.

## Documentation discipline

When changing behaviour, update current docs that describe that behaviour.

Do not let a historical handoff or prototype plan become more authoritative than `SIGNALGATE-STATUS.md`.

If a document is retained only for history, mark it clearly as historical/non-authoritative.

## Scope discipline

Broad new feature building is no longer the default priority.

Prioritise:

1. acceptance evidence;
2. defects revealed by acceptance;
3. security/tenant/reconciliation hardening;
4. provider pilot operability;
5. production-operations evidence.

Do not enable UK retail real-money trading or automatic copy execution as a convenience change.
