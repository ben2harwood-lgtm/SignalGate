# SignalGate Acceptance Evidence Index

Use this file as the control sheet for external/manual acceptance. The public repository may contain **templates and receipt metadata only**. Sensitive reports, credentials, legal advice and customer/provider data belong in the controlled data room.

## Frozen candidate

- Release branch: `release/signalgate-demo-rc-2026-09-19`
- Final evidence/status head: `9499f4e7140b887d0a3c1d136bde8398dd276c9d`
- Runtime candidate recorded in the RC receipt: `6235f136dac3e29d549dc942c998ae7bdacf4e1d`
- Final hardening-spine CI: run **#117** — SUCCESS
- Operating mode: **demo-only**

## Evidence register

| Gate | Required receipt | Template / source | Status | Evidence reference |
|---|---|---|---|---|
| Candidate machine proof | Green full CI at candidate | `docs/RELEASE_CANDIDATE_2026-09-19.md` | Complete | CI #117 / GitHub run 35458021489 |
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

## Rules

1. Do not mark a gate complete because a similar automated test passed.
2. Do not attach secret values to this index.
3. Every receipt must identify the exact candidate/environment it covers.
4. A runtime/source change after an external receipt requires a determination of whether that receipt remains valid; safety-critical MT5/security receipts normally require retest.
5. Findings and exceptions need owners, dates and dispositions.
6. UK retail real-money and automatic-copy modes remain blocked until the corresponding technical/legal gates are explicitly satisfied.

## Controlled data-room naming

A simple convention:

`SG-RC-2026-09-19/<gate>/<YYYY-MM-DD>-<receipt-id>`

Example:

`SG-RC-2026-09-19/mt5/2026-09-20-MT5-001`

Reference that identifier here instead of committing sensitive evidence.
