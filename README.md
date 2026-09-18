# SignalGate

**Provider-agnostic signal execution infrastructure — currently in demo-only hardening.**

SignalGate is being built for signal providers that want a controlled, auditable
path from a provider signal to an authorised customer demo account without
handing raw Telegram text to MetaTrader.

> **Current release state:** demo-only. Do not represent this repository as a
> production live-trading service. See [SIGNALGATE-STATUS.md](SIGNALGATE-STATUS.md)
> and [Release Gates](docs/RELEASE_GATES.md).

## Commercial proposition

> **Your signals. Your customers. Your brand. SignalGate provides controlled
> ingestion, validation, authorisation, execution transport, reconciliation and
> audit.**

SignalGate does **not** provide investment signals and makes no profitability
claim.

## Current architecture

Provider source → deterministic ingestion/validation → stored signal → required
customer authorisation → tenant/account-bound command → MT5 EA or simulator →
execution/management reports → ledger/audit.

The July prototype is intentionally human-in-the-loop: a trade requires explicit
YES approval and the MT5 EA refuses real accounts.

## Already implemented

- Deterministic signal parser for XAUUSD/GOLD/XAU and supported crypto aliases.
- Signal storage, expiry and rejection reasons.
- Per-user YES/NO approval with duplicate-decision protection.
- Structured command output; raw provider text never reaches MT5.
- Demo-only MT5 EA with hard stop, staged TP management and event reporting.
- Python EA simulator that never connects to a broker.
- Audit log and performance ledger.
- Admin pause/resume.
- Per-user hosted licence mechanism.
- PostgreSQL-capable backend.
- GitHub CI, Python compile checks and dependency vulnerability audit on the
  hardening integration branch.

## Hardening work in progress

The active integration branch is
`codex/signalgate-hardening-2026-09-18`.

Independent lanes add:

- strong hosted credentials and fail-closed deployment validation;
- command/account ownership checks and retry-safe execution reporting;
- adversarial parser/input/replay controls;
- provider packaging and release evidence.

PRs are not counted as complete until CI, adversarial tests, review and
acceptance are all green.

## Not yet production-complete

- True organisation/provider/feed multi-tenancy.
- Provider dashboard/onboarding UI.
- Production SSO/MFA/RBAC.
- Versioned database migrations.
- Production observability/SLOs and restore-tested disaster recovery.
- Billing/subscription operations.
- Independent penetration test.
- Written UK regulatory-perimeter opinion for the final operating model.
- Paying provider beta.
- Live retail trading.

Those are release blockers, not hidden limitations.

## Safety model

1. **Demo-only gate:** the EA refuses real accounts.
2. **Human authorisation:** no command is created without the required decision.
3. **Deterministic parser:** ambiguity fails closed.
4. **Structured boundary:** MT5 receives only validated command fields.
5. **Expiry:** stale signals do not create commands.
6. **Idempotency:** duplicate decisions and retry paths must not create duplicate
   execution state.
7. **Pause:** new command creation can be stopped.
8. **Audit:** signal, decision, command and lifecycle events are recorded.

See [Safety Rules](docs/SAFETY_RULES.md) and
[Threat Model](docs/THREAT_MODEL.md).

## Provider Edition

The target provider experience is described in
[Provider Edition](docs/PROVIDER_EDITION.md) and
[Provider Onboarding](docs/PROVIDER_ONBOARDING.md).

The provider-facing sales demonstration deliberately sells control, isolation
and evidence — not trading returns:
[10-minute Provider Demo](docs/SALES_DEMO.md).

## Regulatory gate

The exact role of SignalGate, the provider and the broker must be reviewed
against the intended instruments, customers and order path before any UK
real-money launch. See [UK Regulatory Perimeter Gate](docs/REGULATORY_GATE.md).

## Local demo quick start

Full instructions: [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

```bash
cp .env.example .env

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python ../scripts/init_db.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd telegram_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_bot.py
```

Simulator, no broker and no trading:

```bash
python simulator/ea_simulator.py --user-id USER-000001 --api-key local-demo-ea-key
```

## Tests

```bash
cd backend
python -m pytest -q
```

CI also compiles Python sources and runs `pip-audit` against backend and bot
dependencies.

## Evidence and operations

- [Canonical Status](SIGNALGATE-STATUS.md)
- [Release Gates](docs/RELEASE_GATES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Safety Rules](docs/SAFETY_RULES.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Incident Runbooks](docs/INCIDENT_RUNBOOKS.md)
- [Provider Edition](docs/PROVIDER_EDITION.md)
- [Provider Onboarding](docs/PROVIDER_ONBOARDING.md)
- [UK Regulatory Gate](docs/REGULATORY_GATE.md)
- [Due-Diligence Index](docs/DUE_DILIGENCE_INDEX.md)
- [Testing Plan](docs/TESTING_PLAN.md)
- [Performance Ledger](docs/PERFORMANCE_LEDGER.md)
- [MT5 Setup](mt5_ea/README_MT5_SETUP.md)

## Acquisition discipline

From the first external provider, retain clean evidence for revenue, retention,
support cost, uptime, incidents, security tests, regulatory analysis, customer
concentration, IP ownership and operating runbooks. A future acquirer should be
buying reproducible software and recurring provider relationships — not founder
memory.
