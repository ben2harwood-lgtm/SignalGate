# SignalGate Controlled Provider Pilot

## Purpose

Prove that a real signal provider can operate SignalGate safely and independently on demo infrastructure, while measuring onboarding effort, support load and product reliability. **This is a preparation plan, not approval to activate a provider, broker, or external cohort.**

## First-cohort entry HOLD (25 October 2026)

Before inviting any external provider or subscriber into an actual MT5 demo-broker pilot, require the written, independently reviewed release-entry decision and retained receipts in `docs/BETA_ACCEPTANCE.md`, `docs/MT5_ACCEPTANCE.md`, and the acceptance evidence index. The relevant security, privacy, contract and UK regulatory/financial-promotion entry reviews must be decided for the precise pilot, even if every trading account is demo. Do not treat an internal simulator, synthetic broker snapshot, CI PASS, or a successful compile alone as operator authority.

Frozen RC2 `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2` failed its [exact-source official MetaEditor compile](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898) (**18 errors / 4 warnings**) and cannot be relabelled as a passing broker-demo candidate. Any successor requires an independently reviewed exact candidate SHA/EA hash, a **0-error / 0-warning** official compile, a **nonempty regenerated EX5**, and actual demo-terminal/broker receipts. Execution-safety [PR #60](https://github.com/ben2harwood-lgtm/SignalGate/pull/60) remains **DRAFT/HOLD** for original-order multi-fill/weighted-price proof, deal/order/position IDs, ambiguous restart/reconciliation, and stage-specific TP exits. Unperformed scenarios must remain **NOT_RUN**. No real-money trading or automatic copying is authorised.

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
6. Complete **internal-only simulator** connectivity rehearsal; log synthetic results as such. Simulator success is **not MT5 broker-demo acceptance**.
7. Obtain separately approved, source-bound **actual MT5 demo-broker scenario receipts** and complete mandatory failure scenarios before the first external cohort. Keep each unperformed broker scenario at **NOT_RUN**.
8. Provider/feed pause tested.
9. Sales/demo walkthrough completed.
10. Pilot start receipt recorded.

## Mandatory scenario pack

Before the first cohort:

- exact-candidate independent safety review, official MetaEditor 0/0 log, regenerated nonempty EX5, and actual MT5 demo-broker evidence retained;
- original-order multi-fill/weighted execution, deal-versus-position attribution, uncertain/restart/reconciliation and TP1/TP2/TP3 stage-specific exit proofs reviewed; unresolved PR #60 findings remain HOLD;
- the pilot's applicable independent security/pentest, legal/regulatory, privacy, contract and financial-promotion entry gates reviewed; no production/customer activation implied;
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
