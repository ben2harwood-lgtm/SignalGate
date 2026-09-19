# Provider Edition — 10-minute Sales Demo

The demo sells **control and operating evidence**, not trading returns.

## Minute 0–1 — frame
"SignalGate sits between your signal source and each authorised customer account. You keep the signals, customers and brand; SignalGate makes the execution path controlled, tenant-bound and auditable."

## 1–3 — signal ingestion
Submit a normal demo signal. Show the normalised fields and expiry.
Then submit a deliberately ambiguous signal and show it fail closed.

## 3–5 — subscriber authorisation
Show the subscriber trade card/authorisation step.
Double-submit the approval to demonstrate one-command semantics.

## 5–7 — execution
Use the simulator/demo MT5 account.
Show the structured command, not raw provider text.
Demonstrate that a wrong tenant/licence cannot report that command.

## 7–8 — retry/failure
Replay the execution callback and show it is ignored rather than duplicated.
Show both platform-admin pause and provider/feed-scoped pause. Demonstrate that a paused provider/feed cannot create a new command, and that another provider remains unaffected.

## 8–9 — evidence
Open the signal → approval → command → execution → management/audit timeline.

## 9–10 — provider operation
Show the implemented Provider Edition portal/demo tenant:
- feed health;
- subscriber/account status;
- signal history;
- execution/reconciliation;
- pause;
- export.

## Never demo with
- invented profitability;
- a real-money account during hardening;
- credentials in URLs/screenshots;
- cross-provider shared data;
- unverified "waiting customers" claims.


## Subscriber consent demonstration

Generate a feed invite in the Provider Portal. Show that the provider cannot
directly attach a Telegram id. In a separate subscriber bot chat, accept the
invite with `/join <token>`; only then should the subscriber appear in the
provider feed and become eligible for trade cards.
