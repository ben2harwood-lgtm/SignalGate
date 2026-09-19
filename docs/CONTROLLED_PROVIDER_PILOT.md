# SignalGate Controlled Provider Pilot

## Purpose

Prove that a real signal provider can operate SignalGate safely and independently on demo infrastructure, while measuring onboarding effort, support load and product reliability.

## Suggested pilot shape

- **Duration:** 30 days after technical onboarding.
- **Mode:** demo accounts only.
- **Provider:** one provider tenant, one or more feeds.
- **Subscribers:** small invited cohort; every subscriber explicitly joins a feed.
- **Execution:** per-transaction subscriber authorisation remains required.
- **Evidence:** all signals, decisions, commands, executions, reconciliation events and incidents retained.

## Onboarding milestones

1. Provider organisation and credentials provisioned.
2. Provider rotates initial key.
3. Feed policy configured and paused by default during setup.
4. Provider generates subscriber invites.
5. Subscribers join and receive one-time EA licences.
6. Demo EA/simulator connectivity verified.
7. Mandatory failure scenarios pass.
8. Provider/feed pause tested.
9. Sales/demo walkthrough completed.
10. Pilot start receipt recorded.

## Mandatory scenario pack

Before the first cohort:

- valid signal + YES;
- valid signal + NO;
- parser rejection;
- replay conflict;
- expired signal;
- provider pause;
- feed pause;
- wrong provider credential;
- wrong customer licence;
- execution callback retry;
- broker reconciliation recovery;
- stop-out loss;
- manual/unattributed close;
- encrypted backup/restore CI evidence.

MT5-specific scenarios also require the MetaEditor/demo receipt in `MT5_ACCEPTANCE.md`.

## Measurements

Track at least:

- time to onboard provider;
- time to onboard subscriber;
- support interactions and minutes;
- signals submitted/rejected;
- commands created;
- execution/report failures;
- reconciliation conflicts/recoveries;
- duplicate execution incidents;
- cross-tenant incidents;
- uptime/readiness observations;
- provider active days;
- subscriber participation/retention;
- provider qualitative feedback;
- infrastructure/support cost.

## Pilot exit

A pilot can become a paid recurring deployment only when:

- no unexplained execution or tenant-isolation event remains open;
- all critical/high findings are resolved;
- support burden is understood;
- provider can operate normal tasks without founder-only knowledge;
- G8 external reviews required for the intended next mode are complete;
- commercial/legal terms for that mode are signed.

The pilot is not evidence of investment performance and must not be marketed as such.
