# SignalGate Release Candidate Evidence — RC2 — 19 September 2026

## Candidate identity

- RC2 runtime/tooling SHA: `852a6bc9ca9f0651b34e87b63e86c65669130767`
- Integration branch: `codex/signalgate-hardening-2026-09-18`
- Release branch target: `release/signalgate-demo-rc2-2026-09-19`
- Integrated CI workflow: `SignalGate CI`
- Combined runtime/tooling CI run: **#134**
- GitHub Actions run id: `35459129106`
- Result: **PENDING_FINAL**
- Operating mode: **demo-only**

This receipt records repository evidence. It does **not** claim that external/manual gates are complete.

RC1 remains preserved at `release/signalgate-demo-rc-2026-09-19`. RC2 supersedes RC1 for new acceptance work; RC1 must not be silently rewritten.

## Why RC2 exists

RC1 established a machine-green, substantially built/hardened Provider Edition. Before beginning external acceptance, the repository was pushed through one further readiness pass.

RC2 adds no real-money or automatic-copy mode. It improves how safely and reproducibly the existing demo-only product can be handed to operators, assessors, counsel and a first provider.

### RC2 readiness improvements

- acceptance evidence index and blank receipt templates;
- first-provider operator runbook;
- current Provider Edition demo/onboarding instructions;
- stale Nick/admin-only prototype guides removed from the current operating path;
- stale agent prompts replaced with current Provider Edition guardrails;
- project-owned deprecation warnings cleaned while preserving naive-UTC database semantics;
- deterministic allowlisted external-review bundles;
- SHA-256 manifest for every external-review bundle;
- default bundle verification that checked-out Git HEAD exactly equals the claimed candidate SHA;
- explicit unverified-source escape hatch that marks the manifest unverified;
- hosted deployment docs aligned with Alembic, tenant-scoped auth and encrypted backup/restore;
- first-provider provisioning creates the initial feed paused by explicit API request;
- provider provisioning receipt records the paused state and warns not to unpause before checks pass.

## Machine evidence

The final RC2 runtime/tooling candidate is not accepted until CI run #134 is recorded as SUCCESS.

The same CI matrix covers:

- full backend suite on SQLite;
- full backend suite on PostgreSQL;
- Python source compilation;
- Bandit medium/high static-security scan;
- dependency vulnerability audits;
- PostgreSQL Alembic migration smoke and schema agreement;
- legacy customer-licence plaintext erasure proof;
- audit-hash-chain historical backfill/verification proof;
- hosted stale-schema rejection and re-upgrade;
- hosted container build;
- encrypted PostgreSQL backup + checksum + isolated restore smoke.

The safe-provisioning branch immediately before final integration passed **170 tests on SQLite and 170 tests on PostgreSQL**, with only two upstream framework deprecation warnings. The final combined runtime/tooling CI run #134 is the authoritative integration receipt.

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
- encrypted backup/restore smoke;
- fail-safe paused first-provider feed provisioning;
- acceptance-bundle path/secret allowlist and source-integrity tests.

## Product / pilot package present

The repository now contains:

- repeatable provider provisioning;
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
- first-provider operator runbook;
- acceptance evidence index and receipt templates;
- deterministic external-review bundle tooling;
- dependency/licence inventory procedure;
- due-diligence evidence map;
- penetration-test scope;
- privacy/data map;
- UK regulatory-counsel architecture brief;
- current hosted-deployment/operations guidance;
- current coding-agent safety guardrails.

## External/manual gates still open

### MT5 acceptance

Still required against RC2:

- compile the exact RC2 EA source in target MetaEditor;
- record MetaEditor/build and broker-demo terminal versions;
- prove 0 compile errors and 0 warnings;
- retain screenshot or exported compiler log;
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

RC2 does **not** prove:

- safety for UK retail real-money trading;
- regulatory authorisation or exemption;
- investment performance or profitability;
- production SLO achievement;
- independent penetration-test clearance;
- successful MetaEditor compilation;
- live-broker execution acceptance;
- paying-customer traction.

## RC2 decision

Once run #134 is recorded **SUCCESS** and the documentation-only RC2 freeze itself is green, this candidate is suitable to proceed to the external/manual acceptance sequence.

Do not enable UK retail real-money trading or automatic copy execution from RC2.
