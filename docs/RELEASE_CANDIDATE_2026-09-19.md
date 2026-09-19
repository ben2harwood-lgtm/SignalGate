# SignalGate Release Candidate Evidence — 19 September 2026

## Candidate identity

- Runtime candidate SHA: `6235f136dac3e29d549dc942c998ae7bdacf4e1d`
- Integration branch: `codex/signalgate-hardening-2026-09-18`
- Integrated CI workflow: `SignalGate CI`
- CI run: **#115**
- GitHub Actions run id: `35457806582`
- Result: **SUCCESS**
- Operating mode: **demo-only**

This receipt records repository evidence. It does **not** claim that external/manual gates are complete.

## Final integration sequence

The final release-candidate convergence included:

- PR #33 — stronger newly issued customer EA licences;
- PR #29 — penetration-test scope, privacy/data map and UK regulatory-counsel brief;
- PR #27 — provider provisioning, controlled-beta acceptance, commercial/pilot and due-diligence evidence;
- PR #36 — clean current-spine rebase of the tenant-scoped provider evidence export, superseding conflicted PR #35.

The provider evidence export landed only after the original branch was retargeted, exposed as non-mergeable, rebuilt from the current spine and re-proved. The superseded PR #35 was closed rather than forced.

## Machine evidence at candidate SHA

CI run #115 passed:

- backend test suite on SQLite;
- full backend test suite on PostgreSQL;
- Python source compilation;
- Bandit medium/high static-security scan;
- dependency vulnerability audits;
- PostgreSQL Alembic migration smoke and schema agreement;
- legacy customer-licence plaintext erasure proof;
- audit-hash-chain historical backfill/verification proof;
- hosted stale-schema rejection and re-upgrade;
- hosted container build;
- encrypted PostgreSQL backup + checksum + isolated restore smoke.

The versioned database chain reaches `20260919_0010_audit_hash_chain`.

## Security / isolation evidence present in repository

Automated coverage includes:

- hosted fail-closed configuration and separated credentials;
- hashed provider credentials and customer EA licences;
- provider/feed/subscriber/trading-account tenant ownership;
- cross-tenant negative tests;
- explicit subscriber consent through one-use invites;
- tenant-bound provider Telegram source binding/revocation;
- retry-idempotent execution and management callbacks;
- broker reconciliation and conflict fail-closed paths;
- adversarial parser/replay controls and deterministic fuzz/hostile corpus;
- tamper-evident audit-chain verification;
- provider export privacy/isolation/authentication tests;
- encrypted backup/restore smoke.

## Product / pilot package present

The repository now contains:

- provider provisioning workflow;
- Provider Edition portal and demo bootstrap;
- feed policy, pause and branding controls;
- credential rotation;
- subscriber consent onboarding;
- provider Telegram source onboarding;
- execution/reconciliation history;
- provider evidence export;
- security overview;
- controlled provider beta acceptance checklist;
- controlled pilot plan;
- dependency/licence inventory procedure;
- due-diligence evidence map;
- penetration-test scope;
- privacy/data map;
- UK regulatory-counsel architecture brief.

## Open external/manual gates

### MT5 acceptance

Still required:

- compile the exact candidate EA in target MetaEditor;
- record MetaEditor/build and broker-demo terminal versions;
- prove 0 compile errors and 0 warnings;
- retain screenshot/exported compiler log;
- run and retain the complete demo scenario pack in `docs/MT5_ACCEPTANCE.md`.

Until those receipts exist, MT5 execution is machine-tested but not externally accepted.

### Production operations

Still required before production acceptance:

- central log/metrics backend;
- alert routing and on-call ownership;
- retention configuration;
- measured SLO history;
- scheduled production-like recovery drill with measured RTO/RPO.

### External assurance

Still required:

- independent application/security review;
- penetration test and remediation of critical/high findings;
- UK regulatory-perimeter / financial-promotion advice for the intended operating model;
- privacy/data/contract review.

### Operating evidence

Still required:

- first controlled real-provider demo-account pilot;
- measured onboarding/support/reliability;
- incident disposition;
- paying-provider/retention/economic evidence for a commercially proven operating business.

## Explicit non-claims

This candidate does **not** prove:

- safety for UK retail real-money trading;
- regulatory authorisation or exemption;
- investment performance or profitability;
- production SLO achievement;
- independent penetration-test clearance;
- successful MetaEditor compilation;
- live-broker execution acceptance;
- paying-customer traction.

## RC decision

At `6235f136dac3e29d549dc942c998ae7bdacf4e1d`, the repository is a **machine-green, demo-only software release candidate** suitable to proceed to the external/manual acceptance sequence.

Do not enable UK retail real-money trading from this candidate.
