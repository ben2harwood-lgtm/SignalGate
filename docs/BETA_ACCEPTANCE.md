# SignalGate Controlled Provider Beta Acceptance

A provider enters beta only after every required item below has a retained receipt. **Beta is demo-account only**: G8 legal/assurance evidence does not itself authorise real-money trading, automatic copying, or external activation. This checklist is an operator hold, not an instruction to connect a broker or onboard a provider.

## Current MT5 release-entry HOLD (25 October 2026)

- Frozen RC2 `release/signalgate-demo-rc2-2026-09-19` at `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2` **FAILED** its exact-source official [MetaEditor compile](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898): **18 errors / 4 warnings**. It cannot be used as the approved broker-demo candidate. A later source's successful compile does not retroactively pass this frozen RC2.
- Execution-safety [PR #60](https://github.com/ben2harwood-lgtm/SignalGate/pull/60) remains **DRAFT/HOLD** over original-order multi-fill volume/weighted price, deal/order/position identity, uncertain execution/restart/reconciliation and TP-stage exit attribution. An independently reviewed, separately approved successor and **actual MT5 demo-broker evidence** are required before any execution gate passes.
- Synthetic API snapshots, source assertions, broker-free rehearsal and green CI are **machine evidence only**. Each broker scenario without an actual retained terminal/broker receipt remains **NOT_RUN**, never PASS. Do not infer G3/G8/G9 acceptance from this document.

## Platform gates

- [ ] Hardening integration branch CI green at the candidate SHA.
- [ ] PostgreSQL upgrade/check/downgrade/re-upgrade smoke passes.
- [ ] Dependency audits pass or every exception is documented/time-bounded.
- [ ] Provider A/B cross-tenant negative tests pass.
- [ ] Provider/feed pause paths pass.
- [ ] Replay/ambiguity/idempotency tests pass.
- [ ] Container build passes.
- [ ] Encrypted backup + isolated restore smoke passes.
- [ ] Readiness endpoint and operational metrics verified.
- [ ] No unresolved critical/high security finding from internal review.

## MT5 / execution gate

- [ ] A separately approved successor candidate is selected; **not** the failed frozen RC2. Record its exact Git candidate SHA and EA source SHA-256.
- [ ] Execution-critical source changes have independent code/safety review at the **same exact candidate SHA**, with blocking findings resolved.
- [ ] Official MetaEditor compile on that exact source: **0 errors / 0 warnings**, retained raw log, MetaEditor build, and verified SHA.
- [ ] A **nonempty regenerated EX5** is bound to the compiled EA source and retained receipt; successful CI, logs alone or an older binary cannot stand in for the compiled artefact.
- [ ] Actual MT5 **demo-broker** session receipts identify the exact EA/candidate, broker/demo terminal, demo account (redacted) and command/account provenance. No real account.
- [ ] Original-order **multi-fill** broker evidence proves total filled volume and **weighted execution price**, with correct same-order deal aggregation rather than a single `ResultDeal()`/`ResultVolume()` assumption.
- [ ] Broker **deal/order/position identities** are recorded in their proper domains (e.g. opening deal versus open position ticket), without assuming numerically identical IDs.
- [ ] Ambiguous network sends, partial fills, restart and lost callbacks remain **fail-closed**, with authoritative reconciliation; **no blind resend**, false success or duplicated execution.
- [ ] Specific TP1/TP2/TP3 stage exits have broker exit-deal/reason/volume proof, including partial, stop-out and manual-close negatives; stage markers alone are insufficient.
- [ ] The actual demo-broker scenarios in `docs/MT5_ACCEPTANCE.md` and any applicable stage supplement are retained and reviewed. Mark each unperformed scenario **NOT_RUN** rather than PASS.
- [ ] Normal MARKET demo fill.
- [ ] Broker symbol suffix resolution.
- [ ] LIMIT refusal with no broker order.
- [ ] Broker rejection recorded as failure.
- [ ] Stop-out recorded as loss.
- [ ] Manual/unknown close does not fabricate a TP win.
- [ ] Lost execution callback recovered from broker snapshot.
- [ ] EA restart with open SignalGate position blocks new polling.
- [ ] Reconciliation conflict fails closed.

## Provider onboarding gate

- [ ] Provider legal entity/contact recorded.
- [ ] Organisation/provider tenant provisioned with scripts/provision_provider.py or equivalent admin API calls.
- [ ] Initial provider key delivered through an approved secure channel.
- [ ] Provider rotates the initial key after confirming access.
- [ ] Feed policy configured: symbols, expiry, default lot, pause state.
- [ ] Demo subscriber **accepts a one-time feed invite** and connects their own demo account; a provider cannot silently attach a subscriber.
- [ ] Provider portal overview/history verified.
- [ ] Branding/support contact configured if used.
- [ ] Provider incident/escalation contacts recorded.

## Commercial/legal gate

- [ ] Signed pilot/provider agreement.
- [ ] Data/privacy responsibilities documented.
- [ ] Provider responsibility for signals/strategy documented.
- [ ] Marketing copy contains no unsupported profitability claims.
- [ ] UK regulatory-perimeter advice obtained before any UK retail real-money or auto-copy launch.
- [ ] Financial-promotion review completed for any retail-facing communication in scope.

## Beta scenario pack

Run and retain receipts for:

1. valid signal -> subscriber approval -> command -> demo execution -> close;
2. explicit subscriber rejection;
3. parser rejection;
4. duplicate/replayed source message;
5. provider paused before approval;
6. feed paused before approval;
7. expired signal;
8. wrong provider credential/cross-tenant request;
9. execution callback retry;
10. network-loss reconciliation recovery;
11. stopped-out loss;
12. backup/restore evidence.

## Exit criteria

Do not expand the beta until:

- onboarding time and support effort are measured;
- every incident has a written disposition;
- no unexplained execution or cross-tenant event occurred;
- reconciliation exceptions are understood;
- provider feedback has been triaged;
- external assurance/regulatory gates required for the next operating mode are complete.
