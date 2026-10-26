# SignalGate Provider Edition Demo Script

This walkthrough is an **internal, broker-free Provider Edition rehearsal** on an isolated local demo backend, using synthetic lifecycle events. It is not a real-provider pilot or MT5 demo-broker acceptance test and does not authorise an external release. Genuine MT5 evidence follows a separate approval and receipt process under `docs/MT5_ACCEPTANCE.md`.

## Legacy synthetic CLI containment

`simulator/ea_simulator.py` and `simulator/run_demo_flow.py` post
**fabricated** execution/management events to a backend. They are safe
for isolated local test fixtures, **not** for deployed pilot/customer
environments and **not** for MT5 broker acceptance. Their command-line
entrypoints now refuse non-loopback URLs, URL credentials, redirects and
ambient proxy routing; only numeric `http://127.0.0.1:<port>` or
`http://[::1]:<port>` origins are allowed. They check unpaused,
demo-only `/health` before polling, registering or reporting synthetic
fills. The simulator refuses fake fills after rejected or ambiguous
command acknowledgements, and stops the synthetic lifecycle if execution or
management receipts are rejected. The class-level test harness remains usable
with an in-process FastAPI TestClient. The scripted flow also
halts before the next write when registration, signal creation or approval
does not return an HTTP 200 JSON object with a confirmed, route-safe ASCII
identifier. User, signal and command IDs with URL/path delimiters, escapes,
control characters or excessive length stop the script before the next write;
malformed or rejected receipts are never treated as permission for synthetic fills.
The scripted rehearsal also binds its synthetic poll to the just-approved
command ID: if the backend supplies an older pending command, it stops before
ACK or fake fills. All simulator polls require an HTTP 200 JSON object with
an explicit null or structurally valid command: rejected and malformed poll
responses cannot authorise synthetic acknowledgements or fills. A returned
command must also carry the exact requested demo user ID, an explicit boolean
`demo_only=true`, BUY/SELL direction, explicit `entry_type=MARKET`, and a
route-safe ASCII command ID before the simulator can acknowledge it. Slashes, URL-encoded delimiters,
control characters and oversized command IDs are refused before any synthetic
write; wrong-owner, non-demo or non-MARKET commands cannot produce synthetic
execution. The real demo EA refuses LIMIT entries and invalid/non-positive
stop-loss or TP1 values; this simulator must not fabricate a successful
lifecycle for those malformed commands instead. Pre-ACK guards also reject
non-finite SL/TP1 prices (NaN/Infinity) and missing TP1. Before
any synthetic acknowledgement, the entire returned target list must have
unique TP1-TP3 levels, finite positive prices and finite positive optional
stage lots; lot size and any stated entry price must also be finite and
positive. A malformed TP2/TP3 cannot silently become an absent target or
produce a fake SUCCESS receipt.
Polling can claim the oldest command even on mismatch;
restart only with a clean isolated test database, not a fabricated success.

A loopback URL can still be forwarded by a locally configured tunnel
or reverse proxy: operators must use an isolated test backend/database,
never a forwarded hosted/provider/customer deployment. A green
simulator run never establishes genuine MetaEditor, MT5 demo-broker or
independent acceptance evidence.

## Preflight

1. For **this internal broker-free walkthrough**, use only the local synthetic simulator and an isolated demo backend/database. Treat every actual MT5 broker scenario outcome as `NOT_RUN`; simulator responses are not an alternative acceptance path.
2. **Do not use frozen RC2** (`3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2`) as an MT5 DEMO acceptance candidate. Its exact-source official [MetaEditor run 35464044898](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898) failed with **18 errors / 4 warnings**. A later source's clean compilation cannot retrospectively accept RC2.
3. Any **separately authorised real MT5 DEMO** acceptance work requires an independently approved successor candidate, exact-source 0-error/0-warning MetaEditor receipt, regenerated EX5, resolution of PR #60's multi-fill, deal/position identity, uncertain acknowledgement, split rollback and TP-stage attribution holds, independent review, and **actual MT5 demo-broker scenario receipts**. This walkthrough cannot supply those receipts.
4. Confirm exact-candidate CI and backend readiness for the chosen isolated rehearsal; CI alone is not external acceptance. Use an isolated provider tenant and demo subscriber.
5. Keep provider/feed paused during setup. A real-provider pilot remains **NOT STARTED** and the external feed must stay paused until the broker evidence and **all** `docs/BETA_ACCEPTANCE.md` security, legal, privacy, consent and operator gates are satisfied.

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
7. In this **internal broker-free rehearsal**, the isolated loopback simulator polls for the command.
8. Record any execution/management response as **synthetic only**; actual MT5 demo-broker scenario outcomes remain `NOT_RUN`.
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

For any separately authorised MT5 DEMO acceptance session, follow `docs/MT5_ACCEPTANCE.md` and retain actual exact-candidate broker receipts; none are supplied by this simulator walkthrough.

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
