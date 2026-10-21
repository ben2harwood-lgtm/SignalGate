# SignalGate — Canonical Status

**Ledger updated 21 October 2026.** The RC2 section records the frozen 19 September 2026 candidate; post-RC integration and remaining acceptance gates are tracked below.

## Product position

SignalGate is provider-agnostic, human-authorised signal-execution infrastructure.

> **Your signals. Your customers. Your brand. SignalGate provides the controlled path from validated signal to authorised execution, reconciliation and audit.**

SignalGate does not supply proprietary investment signals, does not promise profitability, and remains **demo-only**. The MT5 EA refuses real accounts.

## Canonical engineering spine

- `main`: active post-RC integration branch (the July prototype has been superseded); it is not the frozen RC2 candidate and is not externally accepted.
- Integration spine: `codex/signalgate-hardening-2026-09-18`.
- Prior frozen RC1: `release/signalgate-demo-rc-2026-09-19` at `9499f4e7140b887d0a3c1d136bde8398dd276c9d`. Preserve it as historical evidence.
- **RC2 runtime/tooling candidate:** `852a6bc9ca9f0651b34e87b63e86c65669130767`.
- RC2 release branch target: `release/signalgate-demo-rc2-2026-09-19`.
- RC2 combined candidate CI: GitHub Actions `SignalGate CI` run **#134** (`35459129106`) — **SUCCESS** at the exact runtime/tooling SHA above.
- The hosted schema is versioned through ten Alembic revisions:
  `20260918_0001` baseline -> `20260919_0002` execution safety -> `0003` replay identity -> `0004` provider tenancy -> `0005` provider branding -> `0006` feed policy -> `0007` customer-licence hashing -> `0008` subscription invites -> `0009` provider-source bindings -> `0010` audit hash chain.

Use RC2 for all new external/manual acceptance work once its final freeze CI is green. RC1 remains an immutable historical checkpoint.

## RC2 improvements over RC1

RC2 does not broaden the trading mode. It improves readiness and evidence quality:

- acceptance evidence index, first-provider operator runbook and blank receipt templates;
- current Provider Edition demo/onboarding documentation, replacing stale Nick/admin-only prototype paths;
- current agent guardrails for Claude/Codex so obsolete prototype instructions cannot override the hardened architecture;
- deterministic allowlisted external-review ZIP bundles with per-file SHA-256 manifests;
- review bundles bind the claimed candidate SHA to the checked-out Git HEAD by default;
- project-owned Python/Starlette deprecation noise reduced from thousands of repeated warnings to two upstream framework warnings;
- hosted deployment documentation aligned with Alembic, tenant auth and encrypted backup/restore;
- first-provider provisioning explicitly creates the initial feed paused;
- final combined RC2 runtime/tooling suite passes **172 tests on SQLite and 172 tests on PostgreSQL**, with only two upstream framework warnings.

## Integrated capability evidence

| Capability | State | Evidence / remaining gate |
|---|---|---|
| Dual-database CI | Integrated | Full backend suite runs on SQLite and PostgreSQL |
| Build/security CI | Integrated | Python compile, Bandit medium/high scan, dependency audit, container build |
| Migration assurance | Integrated | Empty upgrade, schema check, downgrade/re-upgrade, legacy licence erasure and audit-chain backfill proofs |
| Hosted fail-closed auth | Integrated | HTTPS/PostgreSQL/strong-secret requirements; separated admin/bot/provider/customer credentials |
| Customer EA credentials | Integrated | One-time raw value, hash + last-four storage; new licences use stronger four-group format |
| Retry-safe execution lifecycle | Integrated | Owner-bound callbacks, idempotent execution/management reporting, monotonic terminal state |
| Broker-truth execution handling | Integrated | MARKET-only execution, broker retcode checks, symbol suffix resolution, netting fallback |
| Broker reconciliation | Integrated | Lost-callback recovery, restart/open-position gate, conflict fails closed |
| Adversarial ingestion | Integrated | Ambiguity/value/payload/replay controls plus deterministic hostile/fuzz corpus |
| Provider multi-tenancy | Integrated | Organisation/provider/feed/subscriber/trading-account ownership and cross-tenant negative tests |
| Subscriber consent | Integrated | Hashed, expiring, one-use feed invites; direct provider attachment removed |
| Provider Telegram source | Integrated | Feed-bound one-time source binding, revocation and source/feed isolation |
| Provider Edition portal | Integrated | Feed policy, branding, credential rotation, pause, subscribers, history/reconciliation and demo bootstrap |
| Provider evidence export | Integrated | Authenticated tenant-scoped JSON export; credentials/hashes/raw signal text excluded; isolation/privacy tests |
| Audit integrity | Integrated | Tamper-evident SHA-256 hash chain, verifier and historical backfill proof |
| Observability baseline | Integrated | Request correlation/structured logs, protected aggregate metrics, SLO/alert targets |
| Recovery baseline | Integrated | Fail-closed encrypted PostgreSQL backup, checksum and isolated restore smoke |
| Commercial/pilot package | Integrated | Provider provisioning CLI, beta acceptance, controlled-pilot plan, security overview, dependency/licence inventory workflow and due-diligence map |
| Safe provider provisioning | Integrated | New provider feed can be created explicitly paused; provisioning CLI always requests paused state |
| External review packaging | Integrated | Deterministic allowlisted bundles + candidate/source binding + SHA-256 manifest |
| External assurance preparation | Integrated | Pentest scope, privacy/data map and UK regulatory-counsel architecture brief |

## Remaining release gates

These are **not software features to paper over**. They require external or deployed-environment evidence.

1. **MT5 compiler/demo receipt** — compile the exact RC2 `SignalGateEA.mq5` in target MetaEditor with 0 errors / 0 warnings and retain the compiler log/screenshot.
2. **MT5 demo scenario evidence** — run the scenarios in `docs/MT5_ACCEPTANCE.md`, including fill, rejection, suffix, LIMIT refusal, stop-out/manual-close attribution, netting fallback, lost-callback recovery, restart blocking and reconciliation conflict.
3. **Central production telemetry** — connect a real log/metrics backend, alert routing, retention and on-call ownership; then accumulate measured SLO history.
4. **Production-like recovery drill** — retain scheduled restore evidence and measured RTO/RPO, beyond CI smoke.
5. **Independent security assurance** — application/security review and penetration test; remediate critical/high findings.
6. **UK regulatory/legal review** — written advice for the intended operating model, order path and financial-promotion boundaries.
7. **Privacy/contract review** — controller/processor roles, retention/deletion/export duties, subprocessor/transfer terms and provider/pilot agreements.
8. **Controlled provider pilot** — onboard the first real provider in demo-account mode, measure onboarding/support/reliability, triage incidents and retain operating evidence.
9. **Commercial operating evidence** — paying-provider contracts, recurring revenue/retention/support-cost history and a maintained data room.
10. **Real-money retail trading** — remains blocked.

## Gate view

- **G0 Baseline truth:** PASS for the September integration spine.
- **G1 Build integrity:** PASS only at a candidate SHA with green integration CI; rerun after every merge.
- **G2 Identity/access:** machine-green and integrated; external assurance remains part of G8.
- **G3 Execution safety:** core software controls are integrated and machine-tested; **not externally accepted** until real MetaEditor compile + demo execution receipts exist.
- **G4 Adversarial ingestion:** automated parser/replay/fuzz scope is integrated and green; independent security testing can still reveal issues.
- **G5 Provider multi-tenancy:** machine-green and integrated; every future provider-scoped change must retain cross-tenant negative coverage.
- **G6 Production operations:** strong baseline is integrated; **not fully passed** until central telemetry/alerts, measured SLO history and production-like recovery evidence exist.
- **G7 Provider Edition:** substantially integrated, including portal, onboarding/provisioning, consent, Telegram source, pilot package and evidence export.
- **G8 External assurance:** **NOT PASSED**.
- **G9 Controlled provider beta:** **NOT STARTED**.
- **G10 Commercially saleable operating business:** **NOT PASSED**; software packaging is ahead of customer/operating evidence.

## Release interpretation

- **Substantially built/hardened/packaged software:** yes; broad feature building is no longer the priority.
- **Controlled demo-account provider pilot:** technically close, subject to RC2/MT5/external-assurance entry gates.
- **UK retail real-money launch:** no; explicitly blocked.

## Non-negotiable release rules

1. Machine-green is necessary but is not production acceptance.
2. No branch enables real-money retail trading.
3. No schema-changing work lands without an Alembic migration and PostgreSQL proof.
4. No provider-scoped operation may rely on an identifier/header alone as authority.
5. No cross-tenant read/write/broadcast/execute path is acceptable.
6. No broker timeout may trigger a blind resend without authoritative reconciliation.
7. Marketing must describe demonstrated capability, not target-state capability.
8. External evidence must never be represented as complete until the actual receipt/report exists.
9. A frozen candidate is not modified in place; material changes create a new candidate and require appropriate retest.

## 20 October 2026 provider operations work (merged post-RC; not frozen RC2)

A new local candidate adds tenant-scoped daily operational observations to the
Provider Portal. Counts cover the entire command history rather than the recent
history window. Stale report, expired pending and reconciliation review alerts
include oldest outstanding identifiers and explicit sample truncation. Setup and
pause guidance is descriptive; this endpoint grants no pilot/live acceptance.

The parent build run obtained a fresh MetaEditor compile receipt for the unchanged
EA source on 20 October: 0 errors / 0 warnings and a newly generated EX5, with a
negative-control compile that produced errors and no EX5. Working evidence reference:
`work/provider-compile-8bb11393026d4bce925b51cc23d4284f/receipt.json`
(in the coordinating build workspace; retain the packaged receipt with its source
hash before candidate acceptance). This is compiler evidence only, not an MT5
broker-demo scenario receipt or a declaration that frozen RC2's gate is complete.
The provider operations update was merged in PR #71 with successful full integration CI. It does not close broker, independent assurance or real-provider gates.

## 21 October 2026 post-RC integration — evidence only; not release acceptance

The current `main` integration checkpoint is `d684ecf56bdfb5b1ba76ff56875d67db7f2bd7cf`. After PRs #57, #72 and #73 merged, **all 13 reported GitHub CI/security/compiler checks passed** at that exact checkpoint. As before, a future source/runtime change requires a new check. Frozen RC2 remains on its separate release branch and was not modified.

- **Security hardening (#57):** full-history secret scanning, Trivy filesystem/container gates and a hosted image that removes unnecessary pip/setuptools runtime tooling. GitHub CI's image vulnerability scan is green; independent penetration testing remains open.
- **Broker-free rehearsal (#72):** exact-commit archive validation, test/JUnit/source-integrity receipts and a CI job that runs synthetic backend/static-EA scenarios. Every actual broker result is `NOT_RUN`; this does not replace real MT5 scenario testing.
- **Read-only provider preflight (#73):** checks demo-only state, readiness, provider authentication, wrong-key rejection, feed pause, tenant-scoped export and secret-field absence. Receipt candidate SHA is operator-declared, not cryptographically verified against the deployed backend. Conflicted historical PR #56 is closed as superseded.
- **Provider operational observations (#71):** full-history stale execution/reconciliation visibility, tenant-scoped checks and initial feeds paused. This is operational preparation, not pilot acceptance.
- **Safety branch (#60) is NOT merged:** 9/9 machine checks passed on its October 21 safety-test correction, but a reviewer recorded a TP-stage attribution hold: TP1/TP2 currently infer milestones from reduced open-position counts and TP3 can rely on an earlier child's TP exit. Specific broker exit proof and negative regressions remain required before merging.
- **Repository controls:** `main` was unprotected at this checkpoint and the repository was public; issue #49 remains open for branch protection and source-access decisions.

**Do not infer G3, G6, G8, G9 or G10 acceptance from these code/CI improvements.** In particular, the real MT5 demo scenario receipts, independent application/security review and pentest, UK regulatory/privacy/contracts work, deployed monitoring and restore evidence, and a controlled provider pilot remain outstanding. Real-money retail and automatic-copy operation stay blocked.

