# SignalGate Incident Runbooks

## Universal first actions

1. Preserve evidence: timestamps, request ids, command ids, tenant/account ids and logs.
2. Stop new exposure at the narrowest safe scope: account → provider → platform.
3. Do **not** resend an uncertain command.
4. Reconcile intended state against broker state before recovery.
5. Record owner, start time, impact and decisions in the incident log.

## Suspected duplicate execution

- Pause the affected account/provider.
- Fetch original signal, approval, command and all execution attempts.
- Check broker history directly.
- If the broker executed once: repair platform state; do not submit another order.
- If more than once: escalate as critical; apply documented broker/client remediation process.
- Preserve network/retry logs and add the failure to regression tests.

## Backend timeout after order submission

Treat outcome as **unknown**, not failed.

- Do not retry order creation automatically.
- Query/reconcile broker state using command id/magic/comment/account context.
- Mark reconciled state only from evidence.
- Resume only after state matches or an operator explicitly contains the discrepancy.

## Compromised provider credential

- Revoke/rotate provider credential.
- Pause provider feed.
- Review all signals/commands since last-known-good time.
- Check for cross-tenant access attempts.
- Notify affected parties under the incident/privacy procedure where required.
- Re-enable only after root cause and credential hygiene are complete.

## Compromised EA/customer licence

- Deactivate licence.
- Pause new commands for that account.
- Rotate licence after ownership verification.
- Reconcile any commands created/reported during suspected compromise.

## Database failure

- Stop new command issuance.
- Keep broker reconciliation independent of guessed database state.
- Restore into isolated environment from last verified backup.
- Compare audit/broker evidence for the recovery window.
- Reopen only after integrity checks pass.

## Full platform kill

A platform kill must block **new** commands without destroying the evidence needed to manage/reconcile already-open demo positions. Define and test separate controls for:
- stop new signal acceptance;
- stop command creation;
- stop command delivery;
- provider pause;
- account pause.

## Severity

- **SEV-1:** possible unintended/duplicate/cross-tenant execution, credential takeover, material data loss.
- **SEV-2:** provider-wide outage, failed reconciliation, security weakness without known exploitation.
- **SEV-3:** isolated non-safety functional failure.

Every SEV-1/2 produces a written post-incident review and a permanent regression test when technically reproducible.
