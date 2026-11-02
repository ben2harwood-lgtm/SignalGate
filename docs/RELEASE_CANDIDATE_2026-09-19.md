# SignalGate Release Candidate Evidence — RC2 — 19 September 2026

> **RETROSPECTIVE MT5 COMPILER HOLD:** The final frozen RC2 at `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2` passed repository CI but **failed** its official exact-source MetaEditor compilation: **18 errors / 4 warnings** ([run 35464044898](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898)). **Do not use its EA for broker-demo acceptance or change the frozen branch.** This is historical machine evidence, not release approval; an independently reviewed successor requires green exact-source CI, a fresh 0-error / 0-warning MetaEditor compile with matching EX5, and genuine controlled MT5 **DEMO** scenario receipts. See [issue #46](https://github.com/ben2harwood-lgtm/SignalGate/issues/46) and `docs/EXTERNAL_ACCEPTANCE_HANDOFF.md`.

## Candidate identity

- RC2 runtime/tooling SHA: `852a6bc9ca9f0651b34e87b63e86c65669130767`
- Final frozen RC2 SHA: `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2`
- Frozen RC2 final CI: [run 35462909294](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35462909294) — **SUCCESS** (machine checks only)
- Frozen RC2 official MetaEditor: [run 35464044898](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898) — **FAILED, 18 errors / 4 warnings**
- Integration branch: `codex/signalgate-hardening-2026-09-18`
- Release branch target: `release/signalgate-demo-rc2-2026-09-19`
- Integrated CI workflow: `SignalGate CI`
- Combined runtime/tooling CI run: **#134**
- GitHub Actions run id: `35459129106`
- Result: **SUCCESS**
- Operating mode: **demo-only**

This receipt records repository evidence. It does **not** claim that external/manual gates are complete.

RC1 remains preserved at `release/signalgate-demo-rc-2026-09-19`. Frozen RC2 also remains preserved **as historical evidence**, not a candidate for new MT5 broker-demo acceptance. Neither frozen release ref may be silently rewritten.

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

CI run #134 completed **SUCCESS** at the exact RC2 runtime/tooling SHA.

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

The safe-provisioning branch passed **170 tests on SQLite and 170 tests on PostgreSQL**. After the bundle-integrity tests were integrated, final combined CI run #134 passed **172 tests on SQLite and 172 tests on PostgreSQL**, with only two upstream framework deprecation warnings. Run #134 is the authoritative runtime/tooling integration receipt.

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

Still required for an **independently reviewed successor candidate** (not the failed frozen RC2 EA):

- compile the successor's exact pinned EA source in target MetaEditor;
- record MetaEditor/build and broker-demo terminal versions;
- prove 0 compile errors and 0 warnings;
- retain screenshot or exported compiler log;
- run and retain the complete demo scenario pack in `docs/MT5_ACCEPTANCE.md`.

Frozen RC2's actual compiler attempt has already **failed**; do not reclassify it as an unrun or passing gate. A later candidate's successful compilation alone does not constitute real MT5 demo-broker acceptance.

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
- successful MetaEditor compilation (**the official frozen-RC2 attempt failed**);
- live-broker execution acceptance;
- paying-customer traction.

## RC2 decision

Runtime/tooling CI #134 and the final frozen-RC2 CI run `35462909294` are **SUCCESS**, but the frozen release's official MetaEditor run `35464044898` is **FAILED (18 errors / 4 warnings)**. Therefore **frozen RC2 is NOT suitable for MT5 broker-demo acceptance**. Preserve it unchanged. Only a separately designated, independently reviewed successor with green exact-source CI, matching fresh EX5 from a 0-error / 0-warning MetaEditor compile, and genuine controlled demo-broker scenario evidence can progress the relevant acceptance gates. Independent ingress/security, execution safety, legal/privacy and operating gates remain open.

Do not enable UK retail real-money trading or automatic copy execution from RC2.
