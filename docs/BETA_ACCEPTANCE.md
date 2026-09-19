# SignalGate Controlled Provider Beta Acceptance

A provider enters beta only after every required item below has a retained receipt. Beta means sandbox/demo-account operation unless G8 legal/assurance work explicitly permits anything broader.

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

- [ ] MetaEditor compile receipt: 0 errors / 0 warnings.
- [ ] Correct commit SHA recorded in compile evidence.
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
- [ ] Demo subscriber/account attached.
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
