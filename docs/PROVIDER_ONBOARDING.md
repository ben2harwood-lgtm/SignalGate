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


## Subscriber consent

Providers cannot add a registered Telegram user directly.

For each subscriber:

1. In the Provider Portal choose the feed and select **Generate invite**.
2. SignalGate returns a one-time `/join sgi_...` command. The raw token is not stored and is not shown again in later invite listings.
3. Send that invite privately to the intended subscriber.
4. The subscriber opens the SignalGate bot from their own Telegram account and sends the `/join ...` command.
5. The bot authenticates its backend call, registers the subscriber if needed, and the subscriber's acceptance creates the feed subscription + trading account.
6. Only after that acceptance does the subscriber appear in the provider's subscriber list or receive cards for that feed.

Invites expire, can be revoked before acceptance, and cannot be reused. If an invite is forwarded, the first eligible Telegram account that accepts it consumes it, so providers should deliver invites through an appropriate private channel.

The deprecated direct provider enrolment endpoint returns HTTP 410 and creates nothing.


## Telegram signal source

Hosted providers connect Telegram through a feed-bound one-time token rather than a shared provider credential. Generate the token in the Provider Portal, send `/connectprovider <token>` from the provider Telegram account, and verify the binding before submitting screenshots. See `docs/PROVIDER_TELEGRAM_SOURCE.md`.
