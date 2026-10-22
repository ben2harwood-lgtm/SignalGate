# SignalGate Acceptance Evidence Index

Use this file as the control sheet for external/manual acceptance. The public repository may contain **templates and receipt metadata only**. Sensitive reports, credentials, legal advice and customer/provider data belong in the controlled data room.

## Frozen candidate

- Frozen RC2 release ref: `release/signalgate-demo-rc2-2026-09-19` at **`3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2`**; preserve this evidence target.
- Earlier runtime/tooling SHA: `852a6bc9ca9f0651b34e87b63e86c65669130767`; CI #134 / run `35459129106` — **SUCCESS** at that earlier SHA.
- Final frozen RC2 CI: #137 / run `35462909294` — **SUCCESS** at `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2` (machine checks only).
- **MT5 compiler HOLD:** the official harness compiling the exact frozen RC2 EA reported **18 errors / 4 warnings**, recorded in run `35464044898`. A post-RC repair PR #55 compiled successfully at a different SHA; that does not change RC2's failed result.
- Prior RC1: `release/signalgate-demo-rc-2026-09-19` (historical; do not use for new acceptance work)
- Operating mode: **demo-only**

## Evidence register

| Gate | Required receipt | Template / source | Status | Evidence reference |
|---|---|---|---|---|
| Candidate machine proof | Green full candidate CI | `docs/RELEASE_CANDIDATE_2026-09-19.md` | Complete at frozen SHA | Runtime CI #134 / run 35459129106; frozen RC2 CI #137 / run 35462909294 at `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2` |
| MetaEditor compile | 0 errors / 0 warnings, versions + exact candidate SHA | `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md` | **HOLD — frozen RC2 failed** | Official RC2 harness run 35464044898: 18 errors / 4 warnings; issue #46. Post-RC PR #55 is not an RC2 pass. |
| MT5 demo scenarios | Ten scenario results + matching backend/broker evidence | `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md` | Open | |
| Independent security review | Written scope/findings/retest | `docs/PENTEST_SCOPE.md`, `docs/evidence/SECURITY_REVIEW_RECEIPT_TEMPLATE.md` | Open | |
| UK regulatory review | Written advice tied to analysed architecture | `docs/REGULATORY_COUNSEL_BRIEF.md`, `docs/evidence/REGULATORY_PRIVACY_RECEIPT_TEMPLATE.md` | Open | |
| Privacy/contract review | Written decisions / approved terms | `docs/PRIVACY_DATA_MAP.md`, `docs/evidence/REGULATORY_PRIVACY_RECEIPT_TEMPLATE.md` | Open | |
| Central telemetry | Deployed backend, alerts, ownership, retention | `docs/OBSERVABILITY.md` | Open | |
| Recovery drill | Production-like restore + measured RTO/RPO | `docs/BACKUP_RESTORE.md` | Open | |
| Provider pilot entry | All beta-entry gates evidenced | `docs/BETA_ACCEPTANCE.md` | Open | |
| Provider pilot operating evidence | Daily/incident/support/reliability evidence | `docs/evidence/PILOT_OPERATIONS_LOG_TEMPLATE.md` | Open | |
| Exceptions | Explicit owner/rationale/expiry/remediation | `docs/evidence/EXCEPTION_REGISTER_TEMPLATE.md` | Open | |

Frozen RC2's final CI and release-ref pin are complete, but its exact EA **failed** official compilation. Do **not** use frozen RC2's EA for a demo-broker pilot or call its MT5 gate passed. Keep RC2 unchanged; a repaired EA needs a separately identified candidate, exact-source compiler proof and actual demo-broker scenario receipts. Synthetic/backend CI and compilation of a different commit never close those gates.

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
