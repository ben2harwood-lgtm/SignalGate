# SignalGate Provider Edition

## Positioning

SignalGate is infrastructure for signal providers. It is not the signal provider.

**Provider brings:** strategy/signals, customers, brand and any required regulatory permissions.

**SignalGate provides:** controlled ingestion, deterministic validation, customer authorisation workflow, execution transport, guardrails, reconciliation and traceable operational evidence.

## Provider journey

1. Create provider organisation.
2. Create one or more feeds/strategies.
3. Connect a supported source (initially Telegram; API/webhook next).
4. Configure symbols, expiry, execution/risk policy and allowed brokers/accounts.
5. Generate feed-specific subscriber invites.
6. Subscribers accept the one-time invite from their own authenticated bot session, then connect/use their demo-account workflow.
7. Provider sends a signal.
8. SignalGate normalises and validates it.
9. Required user authorisation is collected.
10. A tenant-bound command reaches the correct EA/account.
11. Execution and management events reconcile against intended state.
12. Provider and subscriber see the same audit history.

## Provider dashboard MVP

- Organisation/feed switcher.
- Feed health + last signal.
- Subscribers/accounts status.
- Signal history and rejection reasons.
- Execution/reconciliation timeline.
- Provider-level pause/resume.
- Configuration and key rotation.
- Audit export.
- Support/incident status.

## Commercial packaging

Use a B2B structure rather than taking a percentage of trading gains:

- one-time onboarding/integration fee;
- recurring platform fee;
- usage band by active connected accounts and/or executions;
- enterprise fee for white-label/custom integration/support.

Final prices are a commercial decision after beta evidence establishes onboarding/support cost.

## What we do not sell

- Profitability guarantees.
- Proprietary investment signals.
- "AI trading" claims.
- Fabricated or sample performance presented as real.
- A promise that use of SignalGate changes the risk of trading.

## Acquisition thesis

From customer #1, track the metrics an acquirer can diligence: MRR/ARR, providers, active connected accounts, retention/churn, gross margin, onboarding time, support hours, signals processed, commands executed, reconciliation exceptions, uptime, incidents and customer concentration.
