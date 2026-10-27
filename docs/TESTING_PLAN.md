# SignalGate Testing Plan

SignalGate release evidence is deliberately split into **automated repository proof** and **external/manual acceptance proof**. A green GitHub Actions run is necessary but does not substitute for MetaEditor, broker-demo, penetration-test or legal receipts.

## Automated release-candidate matrix

The `SignalGate CI` workflow runs on every pull request and on pushes to the hardening integration branch.

### 1. Backend suite — SQLite

Runs the complete `backend/tests/` suite against the isolated test database and then compiles Python sources.

Coverage includes:

- deterministic parsing and signal expiry;
- approval/rejection and duplicate-decision safety;
- command claim/report lifecycle and idempotency;
- admin/provider/feed pause controls;
- ledger/audit behaviour;
- hosted authentication and secret handling;
- customer licence issue/rotation/hashing;
- provider organisations, feeds, subscriptions and account isolation;
- subscriber consent invites;
- provider Telegram source binding/revocation;
- Provider Edition portal behaviour;
- provider-scoped evidence export privacy/isolation;
- observability and health/readiness;
- migration/backup helper behaviour;
- audit-chain integrity and tamper detection;
- adversarial ingestion/replay cases;
- MT5 source-level fail-closed invariants;
- simulator end-to-end behaviour.

### Telegram hosted-bot offline wiring smoke

A separate CI job installs `telegram_bot/requirements.txt` into an isolated
Python environment and runs `scripts/verify_telegram_bot_wiring.py`. It
creates a hosted-mode Telegram Application with a forced synthetic token,
checks required command handlers and explicit YES/NO + screenshot callbacks,
and verifies legacy shared-provider enrolment is absent. It also drives
synthetic HTTP 403/404/500, invalid JSON and malformed approval callbacks
through the actual bot helpers: non-2xx and invalid results must never be
presented as confirmed approvals. No bot polling,
network requests, user identities, broker connections or orders occur.

This detects incompatible Telegram/httpx dependency upgrades that backend-only
tests cannot exercise. It is not evidence of real Telegram message delivery,
provider identity or an accepted live pilot.

### 2. Backend suite — PostgreSQL

Runs the same backend suite against PostgreSQL so locking, constraints, tenancy and database-specific behaviour are exercised on the hosted engine.

### 3. Static security

Bandit scans application, Telegram bot, simulator and scripts for medium/high findings. Test fixtures are excluded from the scan.

### 4. Dependency vulnerability audit

`pip-audit` runs against:

- backend dependencies;
- hosted backend dependencies;
- Telegram bot dependencies.

Any accepted exception must be explicit and time-bounded.

### 5. PostgreSQL migration smoke

CI proves the versioned migration chain by:

- upgrading an empty database to head;
- running `alembic check`;
- proving hosted startup accepts the current schema;
- downgrading to the pre-licence-hashing revision, inserting a legacy plaintext customer licence, upgrading and proving plaintext is erased and the hash/last-four are correct;
- downgrading before the audit-hash-chain revision, inserting historical audit rows, upgrading and proving the chain is backfilled and verifies;
- checking the historical baseline shape;
- downgrading to base and proving hosted startup rejects the stale schema;
- re-upgrading to head and rechecking schema agreement.

### 6. Container build

Builds the hosted container from the repository Dockerfile.

### 7. Encrypted backup/restore smoke

CI:

1. creates an ephemeral `age` key;
2. initialises PostgreSQL at migration head;
3. inserts a restore sentinel;
4. creates an encrypted backup and checksum;
5. proves no plaintext dump remains;
6. restores into a separate database;
7. verifies restored data.

This is a CI recovery baseline, not a substitute for a scheduled production-like restore drill with measured RTO/RPO.

## Adversarial/regression focus

Every provider-scoped or execution-boundary change must preserve negative coverage for:

- cross-tenant reads/writes/broadcasts/execution;
- wrong/revoked credentials;
- replayed source messages;
- conflicting parser fields and impossible levels;
- oversized/invalid payloads;
- duplicate decisions and callback retries;
- lifecycle regression after terminal state;
- reconciliation conflicts;
- credential/raw-signal leakage from provider exports;
- audit-chain tampering.

The deterministic parser fuzz/hostile corpus remains part of the automated assurance layer.

### Screenshot vision-response boundary (post-RC)

The image-to-text engine is **not** trade authority. Third-party model/API
responses are untrusted: an explicit JSON boolean `readable: true`, correctly
typed/bounded single-line signal text, accepted confidence/notes fields, and a
valid service content envelope are required for a parseable preview. Malformed
responses, false/unreadable flags, and transport failures produce **empty**
extracted text with non-sensitive operator-facing errors, never a guessed
signal or a raw HTTP exception. The normal deterministic parser and human
provider confirmation remain separate mandatory stages before signal creation.

The combined upstream model response is capped at 8,192 characters before JSON
parsing. A nonempty preview must be printable ASCII only; invisible/bidirectional
Unicode controls, non-ASCII line separators, DEL and trailing control characters
fail closed. Natural-language annotations belong in `notes`, not in the signal
text. These are offline input-boundary checks, not live OCR or MT5 evidence.

`backend/tests/test_vision_extractor_failclosed.py` uses only synthetic JSON
and `httpx.MockTransport` (no external API, customer data, Telegram, EA or
broker connection). These tests prove defensive handling of selected hostile
payloads, **not** the correctness of real model OCR, real provider delivery,
MT5 demo acceptance or external security assurance.

## MT5 acceptance — external/manual

Source-level tests are **not** a MetaEditor compiler receipt.

Before MT5 execution is release-accepted, compile the exact candidate `mt5_ea/SignalGateEA.mq5` in the target MetaEditor and retain:

- MetaEditor/build version;
- broker/demo terminal version;
- candidate commit SHA;
- 0 compile errors;
- 0 compile warnings;
- screenshot or exported compiler log.

Then run and retain receipts for the scenarios in `docs/MT5_ACCEPTANCE.md`, including:

1. normal MARKET fill;
2. broker symbol suffix;
3. LIMIT refusal with no broker order;
4. broker rejection / market closed;
5. stop-loss close correctly attributed;
6. manual/unknown close not fabricated as TP;
7. netting-account fallback;
8. lost callback recovered from broker truth;
9. EA restart with an open SignalGate position blocks new polling until reconciled/flat;
10. conflicting broker snapshot fails closed.

## External assurance

Repository CI cannot close these gates:

- independent application/security review;
- penetration test and remediation evidence;
- deployed central telemetry/alert routing and measured SLO history;
- scheduled production-like recovery drill;
- UK regulatory-perimeter/financial-promotion advice;
- privacy/contract review;
- real-provider demo pilot operating evidence.

## Release rule

A release candidate is accepted only when the candidate SHA, CI run, external receipts and any exceptions are recorded together. **Demo-only remains the enforced operating mode; no automated test result authorises real-money retail trading.**
