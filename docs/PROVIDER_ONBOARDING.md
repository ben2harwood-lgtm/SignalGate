# Provider Onboarding — Target Flow

## Qualification

Collect:
- legal entity and jurisdiction;
- provider brand/contact;
- intended instruments;
- source channel/API;
- target customer type/jurisdictions;
- broker/account types;
- current regulatory status and counsel contact where applicable;
- expected subscribers and signal volume.

Do not collect claims such as "hundreds waiting" as evidence without verifiable customers.

## Sandbox

1. Create isolated provider tenant.
2. Issue scoped provider credentials.
3. Configure one demo feed.
4. Validate sample signals, including deliberate rejects.
5. Connect provider's internal demo subscriber.
6. Run happy path and failure/retry scenarios.
7. Export and review the audit trail together.

## Pilot acceptance

Before external demo users:
- tenant isolation tests pass;
- provider pause works;
- no secret is shared between tenants;
- support owner named;
- regulatory responsibility documented;
- incident contact agreed.

## Production-readiness packet

Provider receives:
- architecture/security overview;
- supported/unsupported behaviour;
- onboarding guide;
- SLA/support policy;
- incident route;
- data/privacy terms;
- responsibility schedule;
- release notes.

SignalGate receives:
- signed agreement;
- verified provider entity/contact;
- configuration approval;
- support escalation contacts;
- beta/pilot success criteria.
