# SignalGate Acceptance Evidence Index

Use this file as the control sheet for external/manual acceptance. The public repository may contain **templates and receipt metadata only**. Sensitive reports, credentials, legal advice and customer/provider data belong in the controlled data room.

## Frozen candidate

- Release branch target: `release/signalgate-demo-rc2-2026-09-19`
- RC2 runtime/tooling candidate: `852a6bc9ca9f0651b34e87b63e86c65669130767`
- Final runtime/tooling CI: run **#134** / GitHub run `35459129106` — **SUCCESS**
- Prior RC1: `release/signalgate-demo-rc-2026-09-19` (historical; do not use for new acceptance work)
- Operating mode: **demo-only**

## Evidence register

| Gate | Required receipt | Template / source | Status | Evidence reference |
|---|---|---|---|---|
| Candidate machine proof | Green full runtime/tooling CI | `docs/RELEASE_CANDIDATE_2026-09-19.md` | Complete | CI #134 / GitHub run 35459129106; RC2 branch is pinned only after freeze CI passes |
| MetaEditor compile | 0 errors / 0 warnings, versions + candidate SHA | `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md` | Open | |
| MT5 demo scenarios | Ten scenario results + matching backend/broker evidence | `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md` | Open | |
| Independent security review | Written scope/findings/retest | `docs/PENTEST_SCOPE.md`, `docs/evidence/SECURITY_REVIEW_RECEIPT_TEMPLATE.md` | Open | |
| UK regulatory review | Written advice tied to analysed architecture | `docs/REGULATORY_COUNSEL_BRIEF.md`, `docs/evidence/REGULATORY_PRIVACY_RECEIPT_TEMPLATE.md` | Open | |
| Privacy/contract review | Written decisions / approved terms | `docs/PRIVACY_DATA_MAP.md`, `docs/evidence/REGULATORY_PRIVACY_RECEIPT_TEMPLATE.md` | Open | |
| Central telemetry | Deployed backend, alerts, ownership, retention | `docs/OBSERVABILITY.md` | Open | |
| Recovery drill | Production-like restore + measured RTO/RPO | `docs/BACKUP_RESTORE.md` | Open | |
| Provider pilot entry | All beta-entry gates evidenced | `docs/BETA_ACCEPTANCE.md` | Open | |
| Provider pilot operating evidence | Daily/incident/support/reliability evidence | `docs/evidence/PILOT_OPERATIONS_LOG_TEMPLATE.md` | Open | |
| Exceptions | Explicit owner/rationale/expiry/remediation | `docs/evidence/EXCEPTION_REGISTER_TEMPLATE.md` | Open | |

RC2 must not be used for external acceptance until the documentation-only freeze branch has also passed the full CI matrix and the named release branch has been pinned.

## Rules

1. Do not mark a gate complete because a similar automated test passed.
2. Do not attach secret values to this index.
3. Every receipt must identify the exact candidate/environment it covers.
4. A runtime/source change after an external receipt requires a determination of whether that receipt remains valid; safety-critical MT5/security receipts normally require retest.
5. Findings and exceptions need owners, dates and dispositions.
6. UK retail real-money and automatic-copy modes remain blocked until the corresponding technical/legal gates are explicitly satisfied.

## Controlled data-room naming

A simple convention:

`SG-RC2-2026-09-19/<gate>/<YYYY-MM-DD>-<receipt-id>`

Example:

`SG-RC2-2026-09-19/mt5/2026-09-20-MT5-001`

Reference that identifier here instead of committing sensitive evidence.
