# SignalGate — Canonical Status

**As of 19 September 2026.** This is the repository truth for release readiness.

## Product position

SignalGate is provider-agnostic controlled signal-execution infrastructure.

> **Your signals. Your customers. Your brand. SignalGate provides the controlled path from validated signal to authorised execution, reconciliation and audit.**

SignalGate does not supply investment signals and must not make profitability claims.

## Canonical engineering spine

- `main`: July demo baseline. Not a production release.
- `codex/signalgate-hardening-2026-09-18`: September integration spine.
- Integrated hardening head after G5 tenancy + operations baseline: `ae75b0e4c13ad90ffbe45c82ee83d36f7ec9f0eb`.
- Versioned hosted migration chain: `20260918_0001` baseline -> `20260919_0002` execution safety -> `20260919_0003` replay identity -> `20260919_0004` provider tenancy.
- Operations baseline: PR #19 integrated at `ae75b0e4c13ad90ffbe45c82ee83d36f7ec9f0eb`; hardening-branch push CI passed.
- Provider/commercial package rebase: this branch/PR; documentation and demo-facing site only, not production UI.

## Integrated capability evidence

| Capability | State | Evidence / remaining gate |
|---|---|---|
| CI + dependency audit | Integrated | GitHub Actions backend tests, compile and dependency audits |
| Hosted fail-closed auth | Integrated | Separate admin/bot/EA credentials; provider-specific DB-backed hashed credentials |
| Execution callback ownership | Integrated | EA reports bound to owning customer licence |
| Retry-safe execution | Integrated | One execution per command, conflicting retries audited/rejected |
| Retry-safe management lifecycle | Integrated | Deterministic idempotency keys + monotonic terminal state |
| PostgreSQL command claim | Integrated | `FOR UPDATE SKIP LOCKED` in hosted path |
| Versioned migrations | Integrated | Alembic baseline + safety + replay + tenancy migrations |
| Adversarial ingestion | Integrated | Ambiguity, malformed values, payload bounds, replay/content-conflict tests |
| Provider organisations/feeds | Integrated | Organisation/provider/feed persisted ownership |
| Provider-specific credentials | Integrated | Raw provider key returned once; only SHA-256 hash stored |
| Subscriber isolation | Integrated | Feed subscriptions + provider-filtered recipient/query paths |
| Trading-account ownership | Integrated | Provider/user account IDs flow onto commands |
| Provider/feed kill switches | Integrated | Approval path fails closed while paused |
| Cross-tenant negative tests | Integrated | Provider A cannot read/broadcast Provider B feed/data |
| Provider API | Integrated | Provisioning, credentials, feeds, subscriptions, pause, tenant-filtered history |
| Container/readiness/backup baseline | Integrated | Non-root image, staging compose, readiness/liveness, checked backup + isolated restore smoke CI |
| Provider dashboard UI | **Not built** | G7 blocker |
| White-label runtime configuration | **Not built** | G7 blocker |
| Demo tenant bootstrap | **Not built** | G7 blocker |
| Broker timeout-after-success reconciliation | **Incomplete** | G3/G6 blocker |
| Full fault-injection campaign | **Incomplete** | G3/G4 assurance blocker |
| Central logs/metrics/tracing/alerts | **Not complete** | G6 blocker |
| Defined SLO/error budget | **Not complete** | G6 blocker |
| Independent penetration test | **Not done** | G8 |
| UK regulatory perimeter opinion | **Not done** | G8 |
| Provider beta | **Not started** | G9 |
| Live retail trading | **Blocked** | Remains demo-only |

## Gate view

- **G0 Baseline truth:** PASS for September integration branch.
- **G1 Build integrity:** PASS on integrated safety/tenancy work; rerun after each subsequent merge.
- **G2 Identity/access:** machine-green and integrated; external security review remains later G8 evidence.
- **G3 Execution safety:** core retry/ownership/state controls integrated; **not fully passed** until MT5 compile/demo receipts and broader fault/reconciliation evidence exist.
- **G4 Adversarial ingestion:** core parser/replay controls integrated; broader fuzz/fault campaign still useful assurance.
- **G5 Provider multi-tenancy:** machine-green and integrated; continue cross-tenant red-team for every provider-scoped change.
- **G6 Production operations:** baseline integrated and machine-green: container/readiness/backup-restore smoke evidence exists. Central observability, SLOs and an exercised operational recovery drill remain open.
- **G7 Provider Edition:** backend API and commercial package exist; **provider dashboard, runtime white-label configuration and demo-tenant UX remain open**.
- **G8 External assurance:** not passed.
- **G9 Controlled provider beta:** not started.
- **G10 Commercially saleable:** not yet; depends on provider beta/customers and complete data room.

## Non-negotiable release rules

1. Machine-green is necessary but not equivalent to production acceptance.
2. No branch enables real-money retail trading.
3. No schema-changing work lands without a reviewed Alembic migration and PostgreSQL smoke evidence.
4. No provider-scoped operation may rely on an ID/header alone as a credential.
5. No cross-tenant query/broadcast/execute path is acceptable.
6. No broker timeout may trigger a blind resend without authoritative reconciliation.
7. Marketing must describe current demonstrated capability, not target-state capability.

