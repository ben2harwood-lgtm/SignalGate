# SignalGate Provider Edition Demo Script

This walkthrough demonstrates the current Provider Edition journey without real money. It is for sales/pilot demonstration and operating rehearsal; it is not a substitute for the MT5 acceptance scenarios in `docs/MT5_ACCEPTANCE.md`.

## Preflight

1. Use the frozen demo-only RC or a later explicitly named candidate.
2. Confirm backend readiness and green candidate CI.
3. Use an isolated provider tenant and demo subscriber.
4. Keep the provider/feed paused while configuring.
5. Use demo MetaTrader or the simulator only.

## Provider setup

1. Provision the provider tenant using `scripts/provision_provider.py` or the equivalent authenticated admin workflow.
2. Deliver the initial provider credential through an approved private channel.
3. Provider connects to the Provider Portal and rotates the initial credential.
4. Configure:
   - provider display/support details;
   - one demo feed;
   - feed symbol allowlist;
   - expiry;
   - default lot size;
   - paused state.
5. In the Provider Portal generate a one-time Telegram source token for the feed.
6. From the provider's Telegram account send:
   `/connectprovider <one-time-token>`
7. Verify that the source binding appears for the intended provider/feed.

## Subscriber consent

1. Provider generates a one-time subscriber invite for the demo feed.
2. Send the private `/join sgi_...` command to the intended demo subscriber.
3. Subscriber opens the SignalGate bot from their own Telegram identity and sends the join command.
4. Confirm the subscriber now appears only inside the correct provider/feed.
5. Capture the subscriber's one-time EA licence through the approved onboarding path; do not paste it into screenshots or shared logs.

The provider must not directly attach a subscriber behind the subscriber's back.

## Happy-path signal

1. Provider submits a clear demo signal from its bound Telegram source.
2. SignalGate extracts/parses it and presents the structured preview.
3. Provider confirms only after checking symbol, direction, entry, stop and targets.
4. The subscribed tester receives the structured trade card.
5. Tester presses **YES**.
6. SignalGate creates one tenant/account-bound command.
7. Demo EA or simulator polls for the command.
8. Execution is reported from demo broker/simulator state.
9. Management events progress through the lifecycle.
10. Provider opens history/reconciliation in the Provider Portal.
11. Download the tenant-scoped provider evidence export.

## Failure/safety demonstrations

Demonstrate at least:

- subscriber presses **NO** — no command;
- duplicate YES — no duplicate command;
- expired signal — no command;
- malformed/ambiguous signal — rejected;
- provider paused — approval fails closed;
- feed paused — approval fails closed;
- replayed source message — no second signal;
- wrong/revoked provider credential — rejected;
- wrong customer licence — rejected;
- reconciliation conflict — fails closed.

For MT5 demonstrations also follow `docs/MT5_ACCEPTANCE.md` and retain the formal receipt.

## Evidence to show

The demo should make the control system visible:

- provider/feed identity;
- subscriber consent;
- explicit per-transaction authorisation;
- parser rejection reason;
- pause controls;
- one-command/idempotency behaviour;
- execution/reconciliation history;
- audit/history evidence;
- provider evidence export.

Do not sell the demonstration as evidence of profitability, regulatory clearance or production-live readiness.
