# Audit Integrity

SignalGate's audit log is tamper-evident.

## Chain

Each audit row stores:

- `prev_hash`: the prior audit row's hash;
- `record_hash`: SHA-256 over the exact stored id, event type, entity type/id, payload string, timestamp and prior hash.

Rows are ordered by `created_at, id`.

On PostgreSQL, audit appends take a transaction-scoped advisory lock before reading/writing the chain head. This serialises concurrent chain-head updates without introducing an external queue.

## Verification

Admin API:

    GET /admin/audit/verify

Operator CLI:

    cd backend
    python scripts_verify_audit_chain.py

A valid nonempty receipt includes the row count and current 64-character head hash. A changed payload, changed timestamp, deleted/reordered row, changed previous hash or changed record hash causes verification to fail and identifies the first broken row, provided a trustworthy earlier chain head is retained for comparison when needed.

**Empty-chain evidence rule:** the core API's `valid: true` with `count: 0` and `head_hash: null` is a vacuously consistent chain, **not** proof that operational audit history exists. The operator CLI now emits an explicit `nonempty_chain_verified` boolean and exits:

- `0` for an internally valid **nonempty** chain with a SHA-256 head;
- `1` for a broken/invalid chain;
- `2` for an inconclusive empty/missing-head receipt.

An operator must not treat `valid: true, count: 0` or a CLI exit `2` as an acceptance pass. A green CLI exit **does not itself** attest the selected database identity, the deployed candidate, completeness of historical events or independent tamper resistance; preserve independent head-hash receipts and environment/candidate bindings separately in the controlled data room.

## Migration

Migration `20260919_0010` backfills the existing audit history in deterministic chronological/id order before making `record_hash` non-null and unique.

CI downgrades to `0009`, inserts pre-chain historical rows, upgrades to head and verifies the resulting chain.

## Scope and limitation

This is **tamper evidence**, not magic immutability. A sufficiently privileged database actor who rewrote every affected row and recomputed the entire chain could manufacture a new internally consistent history. Deleting *all* audit rows also produces an internally consistent empty chain. Only comparison against a separately retained prior head/row-count receipt can demonstrate that such removal was unexpected.

For stronger external evidence, retain periodic chain-head hashes outside the primary database (for example in signed release/operations receipts or an independent log store). Production access controls, backups and external telemetry remain part of the assurance model.
