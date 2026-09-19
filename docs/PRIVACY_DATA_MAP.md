# SignalGate Privacy and Data Map

This is an engineering inventory for privacy/legal review, not a final privacy policy or legal retention determination.

## Data categories

| Data | Purpose | Typical source | Sensitivity / notes |
|---|---|---|---|
| Telegram user id | subscriber identity/routing | Telegram bot | persistent identifier |
| Telegram username / first name | support/onboarding display | Telegram bot | personal data |
| Provider organisation/name/contact | B2B tenant/support | provider/admin | business/contact data |
| Provider API key | provider authentication | SignalGate | raw shown once; hash stored |
| Customer EA licence | customer EA authentication | SignalGate | raw shown once after hashing lane; hash + last4 stored |
| Signal raw text | execution instruction/audit | provider | may contain provider-authored content; avoid unrelated personal data |
| Parsed symbol/direction/levels | validation/execution/audit | SignalGate | trading instruction data |
| Subscriber approval | authorisation evidence | subscriber via bot | decision/timestamp |
| Command/account ownership ids | execution routing/audit | SignalGate | internal identifiers |
| Broker tickets/prices/lot/slippage | reconciliation/evidence | EA/broker | financial/trading activity data |
| Management events | lifecycle/audit | EA/broker | trading activity data |
| Performance ledger | truthful outcome record | SignalGate | trading-performance data |
| Audit log | security/operational evidence | SignalGate | may include identifiers; secrets prohibited |
| Request telemetry | availability/security | backend | path/status/latency/request id only; no query/header/body values |
| Backups | recovery | PostgreSQL | encrypted full database copy |

## Trust/data flows

1. Provider -> ingestion API/bot -> signal parser -> PostgreSQL.
2. Subscriber -> Telegram bot -> authenticated registration/decision API.
3. Backend -> tenant-bound command -> customer EA.
4. EA/broker -> execution/management/reconciliation callbacks -> PostgreSQL/ledger.
5. Provider portal -> tenant-scoped provider APIs.
6. Admin/operator -> admin API/metrics/runbooks.
7. PostgreSQL -> encrypted age backup -> retained backup storage.
8. Backend -> structured logs/metrics -> future central telemetry backend.

## Current minimisation controls

- provider raw keys are not stored;
- customer raw licences are being migrated to one-way hashes;
- credentials are excluded from URLs and audit payloads;
- request logging excludes query strings, headers and bodies;
- provider queries are server-side tenant filtered;
- portal displays only provider-owned subscriber metadata;
- backup artifacts use fail-closed age public-key encryption in the integrated operations baseline.

## Decisions required before external beta expansion

Privacy/legal review must determine:

- controller/processor roles for SignalGate vs providers;
- lawful bases and required notices;
- exact retention periods by data class/jurisdiction;
- deletion/export obligations;
- provider access to subscriber profile fields;
- incident/breach notification responsibilities;
- subprocessor list and international transfer requirements;
- whether trading-performance/account activity has additional contractual/regulatory restrictions.

## Engineering release rule

Do not invent retention periods merely to fill a policy. Until reviewed, preserve required audit/security evidence, minimise new collection, support deletion/export design, and keep demo/test data clearly separable from any future live account data.
