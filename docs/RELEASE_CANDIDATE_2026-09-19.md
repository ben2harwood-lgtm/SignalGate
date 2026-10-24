# SignalGate Release Candidate Evidence — RC2 — 19 September 2026

## Candidate identity

- RC2 runtime/tooling SHA: `852a6bc9ca9f0651b34e87b63e86c65669130767`
- Integration branch: `codex/signalgate-hardening-2026-09-18`
- Release branch target: `release/signalgate-demo-rc2-2026-09-19`
- Integrated CI workflow: `SignalGate CI`
- Combined runtime/tooling CI run: **#134**
- GitHub Actions run id: `35459129106`
- Result: **SUCCESS**
- Operating mode: **demo-only**

This receipt records repository evidence. It does **not** claim that external/manual gates are complete.

> **Post-freeze correction — 24 October 2026 (not a change to frozen RC2):**
> The exact frozen RC2 release source `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2`
> subsequently **FAILED** the official MetaEditor compilation: **18 errors, 4 warnings**
> ([frozen-source compiler run 35464044898](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898)).
> The successful repository CI run #134 / `35459129106` is **machine CI only**; it is
> not a MetaEditor pass. **Frozen RC2 must not be used for MT5 broker-demo
> acceptance.** A repaired post-RC source compiled separately, but that does not
> retroactively pass or modify RC2. See draft PR #60 for still-unresolved
> broker-execution attribution/reconciliation holds. All actual broker-demo
> scenarios remain **NOT_RUN**, not accepted. This dated correction supersedes
> any prospective acceptance wording in the original September receipt.

RC1 remains preserved at `release/signalgate-demo-rc-2026-09-19`. RC2 superseded RC1 as the September machine-evidence candidate, not as permission for new broker-demo acceptance after its failed exact-source compile. Neither frozen branch may be silently rewritten.

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

**Frozen RC2 cannot pass this gate:** its exact-source MetaEditor compile has
already failed (18 errors / 4 warnings, run `35464044898`). Do not run the frozen
EA for MT5 broker-demo acceptance. A later repaired post-RC compile is not
evidence of a retroactive RC2 pass.

Before any **new, separately pinned and independently reviewed successor**
could enter controlled **DEMO-account** broker acceptance, retain:

- exact successor SHA with fresh integration/security CI and independent review;
- official MetaEditor/build version, 0 compile errors and 0 warnings;
- a **newly generated EX5** proven to belong to that exact source/compile;
- broker-demo terminal version and the complete scenario receipts in `docs/MT5_ACCEPTANCE.md`;
- explicit resolution of draft PR #60's outstanding execution attribution,
  multi-fill and reconciliation holds, with negative tests and real demo evidence.

There is no MT5 broker-demo acceptance receipt: scenarios remain **NOT_RUN**.
Machine tests and official compilation alone do not substitute for broker truth;
no real-money or automatic-copy execution is authorised.

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
- successful MetaEditor compilation (the exact frozen EA is **known to have failed**);
- MT5 demo-broker execution acceptance (scenarios **NOT_RUN**);
- paying-customer traction.

## RC2 decision

Run #134 was **SUCCESS** for September repository machine CI only. The later
official **exact frozen-source MetaEditor compile FAILED** (run
`35464044898`). Therefore frozen RC2 is **not an eligible MT5 broker-demo
acceptance candidate**. Preserve this receipt as historical machine evidence;
use a separately pinned, reviewed and retested successor for any future controlled
DEMO-account acceptance, after its compiler and execution safety holds are cleared.

Do not enable UK retail real-money trading or automatic copy execution from RC2.
