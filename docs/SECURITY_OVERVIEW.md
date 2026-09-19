# SignalGate Security Overview

This document describes the current repository controls, not a certification.

## Security boundaries

### Tenant identity

Provider Edition persists organisation -> provider -> feed -> subscription -> trading-account ownership. Hosted provider requests use a provider id plus a provider-specific API key. The raw provider key is returned only when issued/rotated; storage keeps a one-way SHA-256 hash.

Every provider-facing feed, subscriber, signal and command query is server-side tenant filtered. Cross-tenant negative tests are part of CI.

### Customer EA identity

The EA uses a platform EA API key plus the customer's licence in headers. Hosted callbacks are bound to the customer that owns the command. Licence secrets are not placed in URLs.

### Admin/bot boundaries

Hosted mode separates admin, registration/bot, provider and EA credentials. Hosted startup refuses SQLite, HTTP backend URLs, weak service secrets and non-demo mode.

## Execution integrity

- PostgreSQL command claims use row locking / SKIP LOCKED.
- First execution reports are accepted only after EA claim.
- One execution row per command is database-enforced.
- Duplicate retries are idempotent.
- Contradictory retries are rejected and audited.
- Management lifecycle retries use deterministic idempotency keys.
- Terminal command state cannot be reopened by late lifecycle events.
- Broker-position reconciliation can recover a lost callback only when owner/symbol/direction state agrees; contradictions fail closed.
- Provider/feed/global pauses block new command creation.

## Ingestion integrity

- deterministic fail-closed parsing;
- conflicting signal fields rejected;
- non-positive and dangerous numeric formats rejected;
- source-message replay uniqueness;
- same replay identity with different content is an audited conflict;
- request/image bounds and media-type checks;
- tenant/feed source namespaces.

## Database and deployment

- hosted PostgreSQL schema is Alembic-managed;
- startup refuses a stale migration revision;
- migration CI exercises empty upgrade, schema check, historical baseline, downgrade and re-upgrade;
- backend container runs non-root;
- readiness requires a database round trip;
- staging compose exists separately from local demo mode.

## Backup/recovery

The integrated operations baseline uses age public-key encryption, checksum verification, fail-closed plaintext handling, and an isolated encrypted backup/restore smoke in CI. A production-like scheduled restore drill with recorded RTO/RPO is still required.

## Observability

The integrated observability baseline provides request correlation IDs, structured request logs without query/header/body values, protected aggregate metrics and defined alert/SLO targets. A central telemetry backend, alert routing and measured SLO history remain deployment work.

## Known external assurance gaps

Before G8 passes:

- independent application/security review;
- penetration test and remediation;
- final MetaEditor compile/demo receipts;
- UK regulatory-perimeter/financial-promotion advice for the intended operating model;
- privacy/DPA/retention review;
- production identity controls such as SSO/MFA/RBAC if required by target enterprise customers.

## Scope

Current repository policy remains demo-only. Nothing in this overview authorises live retail trading.
