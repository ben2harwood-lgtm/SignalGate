# Windows VPS Setup — Historical Local-Demo Rehearsal Only

This file previously described a one-box Windows/SQLite/shared-secret solo test.

That is **not** the current hosted Provider Edition deployment model and must not be used for a real provider pilot.

For current operation use:

- `docs/HOSTED_DEPLOYMENT.md`
- `docs/FIRST_PROVIDER_RUNBOOK.md`
- `docs/PROVIDER_ONBOARDING.md`
- `docs/PROVIDER_TELEGRAM_SOURCE.md`
- `docs/MT5_ACCEPTANCE.md`

## What the old one-box pattern is still suitable for

A private, isolated **local demo rehearsal** can put backend, bot, simulator/MT5 and SQLite on one Windows machine for developer convenience.

If you do that:

- demo broker account only;
- no provider/customer real data;
- no claim that local auth/storage equals hosted security;
- no shared provider invite code presented as production auth;
- do not use it as penetration-test or production-operations evidence.

The current Provider Edition pilot uses PostgreSQL, hosted fail-closed settings, tenant-scoped provider credentials, subscriber consent invites and feed-bound Telegram source bindings.

The frozen release candidate and external acceptance documents remain authoritative.
