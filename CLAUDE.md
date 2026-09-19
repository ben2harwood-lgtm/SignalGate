# SignalGate — Claude / Coding-Agent Context

Read `AGENTS.md` first. It contains the authoritative current engineering and safety rules.

## Canonical context

SignalGate is no longer a local-only prototype. It is a demo-only Provider Edition with tenant-scoped provider/feed/subscriber/account ownership, explicit subscriber consent and per-transaction authorisation, provider Telegram source binding, retry-safe execution, broker reconciliation, Provider Portal/evidence export, audit integrity, PostgreSQL migrations, observability and encrypted recovery baselines.

Current truth:

- `SIGNALGATE-STATUS.md`
- `docs/RELEASE_CANDIDATE_2026-09-19.md`
- `docs/TESTING_PLAN.md`
- `docs/EXTERNAL_ACCEPTANCE_HANDOFF.md`
- `docs/ACCEPTANCE_EVIDENCE_INDEX.md`

Frozen demo RC:

`release/signalgate-demo-rc-2026-09-19`

Do not move or rewrite the frozen candidate while external evidence is being collected.

## Before editing

- inspect the actual current branch/head;
- read the relevant tests and current docs;
- do not trust old prototype/handoff statements over canonical status;
- keep changes narrow;
- preserve demo-only, tenant-isolation, consent, idempotency and reconciliation invariants;
- never print/commit `.env` or credentials.

## Legacy flows not to restore

Do not treat these as current hosted architecture:

- shared provider invite code / `/provider <code>`;
- direct provider attachment of subscribers;
- guessed sequential user ids;
- plaintext licences/provider keys;
- local-demo auth shortcuts in hosted mode;
- blind broker retry;
- auto-copy without per-transaction approval.

## Acceptance

Full CI is required for integration. External/manual gates remain external; never fabricate them from source review or unit tests.

For the next-stage work, prefer acceptance/pilot readiness and defects found by those gates over broad feature expansion.
