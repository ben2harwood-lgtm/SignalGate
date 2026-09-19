# SignalGate — Current Install & User Guide

SignalGate is now a **provider-agnostic, tenant-scoped, demo-only** platform. This guide routes each role to the correct current workflow instead of reproducing historical prototype instructions.

> **Do not use real-money accounts.** The frozen demo release candidate is `release/signalgate-demo-rc2-2026-09-19`.

## 1. Choose your path

### Local developer / simulator

Use this when proving backend, bot and lifecycle behaviour without a broker:

- `docs/LOCAL_SETUP.md`
- `docs/DEMO_SCRIPT.md`
- `simulator/ea_simulator.py`

Local-demo compatibility paths are development conveniences. They are not the hosted Provider Edition security model.

### Provider Edition operator

Use:

- `docs/HOSTED_DEPLOYMENT.md`
- `docs/FIRST_PROVIDER_RUNBOOK.md`
- `docs/PROVIDER_ONBOARDING.md`
- `docs/PROVIDER_TELEGRAM_SOURCE.md`
- `docs/BETA_ACCEPTANCE.md`

The operator provisions an isolated organisation/provider/feed, delivers the one-time provider credential privately, and keeps the feed paused until source/subscriber/demo-execution checks pass.

### Signal provider

The provider:

1. receives access to its own provider tenant;
2. rotates its initial provider credential;
3. configures its feed in the Provider Portal;
4. generates a one-time feed-bound Telegram source token;
5. sends `/connectprovider <token>` from the intended provider Telegram identity;
6. generates private subscriber invites;
7. reviews/confirm signals before broadcasting;
8. can pause its own provider/feed;
9. reviews history/reconciliation and can download its tenant-scoped evidence export.

Do not use the old shared `/provider` invite-code flow.

### Subscriber / demo tester

The subscriber:

1. receives a private one-time `/join sgi_...` feed invite;
2. sends it from their own Telegram account;
3. appears in the provider feed only after explicit join/consent;
4. receives structured trade cards;
5. presses YES or NO per transaction;
6. uses the assigned one-time customer EA licence for the demo execution account.

A provider cannot silently enrol a subscriber through the deprecated direct-attachment path.

### MT5 tester

Use:

- `mt5_ea/README_MT5_SETUP.md`
- `docs/MT5_ACCEPTANCE.md`
- `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md`

Compile the exact candidate source in MetaEditor and retain 0-error / 0-warning evidence before treating the MT5 lane as externally accepted.

## 2. Local demo quick start

For local development only:

```bash
cp .env.example .env

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python ../scripts/init_db.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the bot in another shell:

```bash
cd telegram_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_bot.py
```

Use `docs/LOCAL_SETUP.md` for platform-specific detail and the simulator before involving MT5.

Never commit or share the resulting `.env`.

## 3. Hosted / provider environment

Hosted mode is materially stricter than local demo mode.

Use `.env.hosted.example` and `docs/HOSTED_DEPLOYMENT.md`. Hosted startup expects the configured security/database invariants and the versioned Alembic schema.

Important current controls include:

- PostgreSQL hosted database;
- versioned Alembic migrations;
- separated admin/bot/provider/customer credentials;
- hashed provider credentials and customer EA licences;
- provider/feed/subscriber/trading-account ownership;
- explicit subscriber consent invites;
- provider Telegram source bindings;
- provider/feed pause controls;
- audit hash chain;
- structured request logs/protected metrics;
- encrypted backup/restore baseline.

Do not copy local-demo shared secrets/identity shortcuts into hosted operation.

## 4. Current provider demonstration

Follow `docs/DEMO_SCRIPT.md`.

The current journey is:

`provider tenant -> feed policy -> provider Telegram binding -> subscriber join -> signal preview/confirm -> subscriber YES/NO -> tenant/account-bound command -> demo EA/simulator -> execution/reconciliation -> evidence export`

The sales/demo emphasis is control, isolation, explicit authorisation, evidence and failure behaviour—not returns.

## 5. MT5 setup

The authoritative setup is `mt5_ea/README_MT5_SETUP.md`.

Key rules:

- demo account only;
- exact backend URL must be allowlisted in MT5 WebRequest settings;
- customer/account identity and licence must match the subscriber/account owning the command;
- keep the EA's demo-only guard enabled;
- use the formal MT5 acceptance scenarios for release evidence.

Do not guess user ids or reuse one customer's licence for another customer.

## 6. Evidence and external review

The release/acceptance control plane is:

- `SIGNALGATE-STATUS.md`
- `docs/RELEASE_CANDIDATE_2026-09-19.md`
- `docs/ACCEPTANCE_EVIDENCE_INDEX.md`
- `docs/EXTERNAL_ACCEPTANCE_HANDOFF.md`
- `docs/REVIEW_BUNDLES.md`

Sensitive external reports/advice and credentials belong in the controlled data room, not this public repository.

## 7. Safety failures that stop the pilot

Pause/stop and investigate if you see:

- unexplained duplicate broker execution;
- cross-tenant read/write/execution;
- execution state inconsistent with broker truth;
- unexplained reconciliation conflict;
- credential exposure;
- real-account execution attempt;
- critical/high security finding that applies to the pilot mode.

Use `docs/INCIDENT_RUNBOOKS.md`.

## 8. What is historical

Older prototype material may describe:

- one admin sending every signal;
- each user making their own bot;
- a shared `SIGNAL_PROVIDER_INVITE_CODE`;
- `/provider <code>`;
- guessed sequential `USER-000001` ids;
- SQLite/local secrets as if they were hosted architecture.

Those patterns are not the current Provider Edition operating model. When documentation disagrees, use the canonical status/current runbooks above and treat historical handoffs/plans as non-authoritative.
