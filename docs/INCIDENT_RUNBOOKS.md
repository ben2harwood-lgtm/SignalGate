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

## MT5 DEMO partial-fill or broker identity uncertainty — HOLD

Trigger this procedure if an original order may have filled in multiple deals,
an execution callback reports less than the broker's complete opening volume,
a restart/close cannot be tied to the original order, or an opening **deal
ticket** is being compared to a current **position ticket**. These are
unresolved acceptance risks in draft PR #60; neither source-level tests nor
a clean MetaEditor compilation settle them.

1. **Pause new command creation/delivery** at the affected account/feed/provider
   using existing controls. A platform pause does not close an open broker
   position. Preserve broker exposure for an authorised operator to assess;
   do not issue a speculative offsetting order.
2. Identify the exact **DEMO account**, SignalGate command, original broker
   order (`DEAL_ORDER`), **every** opening deal ticket and its
   `DEAL_POSITION_ID`, the stable position identity
   (`POSITION_IDENTIFIER`) and current position ticket
   (`POSITION_TICKET`). Retain time, symbol, side, lots and broker
   retcodes for each. **Do not equate** a deal ticket and a position ticket:
   they are different identity domains even if a synthetic fixture gives
   them the same number.
3. Reconcile **all opening deals** against the original order before asserting
   total filled volume or a volume-weighted execution price
   (sum of deal price × deal lots / sum of deal lots). Reconcile all closing
   deals and broker-reported exit reasons before attributing TP1/TP2/TP3,
   stop-out, manual close or remaining open volume. A decrease in position
   volume is not itself proof of a TP-stage exit.
4. Until every link, fill and exit is resolved, retain the incident as
   **UNKNOWN / RECONCILIATION REQUIRED** in the operator record. Do not
   invent, overwrite or certify a backend `SUCCESS`, `FULLY_CLOSED`,
   broker `MATCHED` or TP-stage receipt to make the systems agree. Preserve
   conflicting original records and request independent reconciliation review.
5. **Never blindly resend** after an uncertain acknowledgement or possible
   fill. Do not use automatic copying, a restart or an unverified split
   rollback as recovery. Any emergency broker/client position management is
   a separate explicitly authorised DEMO-account decision with its own
   evidence; this runbook initiates no broker action.
6. Store actual broker history, relevant redacted audit/ledger/API records,
   original-order/deal/position mapping, candidate commit and EA-source hashes,
   terminal/MetaEditor build, incident owner and disposition in a **private**
   evidence store. Put receipt references, not account IDs, credentials,
   personal data or broker statements, into the public evidence index.

**Acceptance remains OPEN:** frozen RC2's exact-source official MetaEditor
compile failed (18 errors / 4 warnings; run `35464044898`). Later clean
compiler results do not retroactively repair RC2. Actual controlled MT5
DEMO broker scenarios remain `NOT_RUN` until supported by their own
exact-candidate receipts and independent review. Do not mark G3 or an
external pilot accepted from this incident runbook.

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
