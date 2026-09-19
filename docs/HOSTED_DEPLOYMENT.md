# SignalGate — Hosted Provider Edition Deployment

This is the current hosted-deployment guide for the hardened **demo-only** Provider Edition.

It does not itself prove production acceptance. Use `SIGNALGATE-STATUS.md` and `docs/EXTERNAL_ACCEPTANCE_HANDOFF.md` for remaining gates.

## 1. Deployment shape

Hosted SignalGate separates:

- public TLS/reverse-proxy edge;
- FastAPI backend;
- shared Telegram bot service;
- PostgreSQL;
- provider tenants/feeds;
- subscriber/customer demo EA clients.

Only the reverse proxy/hosting edge should be public. The backend should bind privately/loopback inside the deployment network.

Use:

- `.env.hosted.example`;
- `docs/OPERATIONS.md`;
- `docs/DATABASE_MIGRATIONS.md`;
- `docs/BACKUP_RESTORE.md`;
- `docs/OBSERVABILITY.md`.

## 2. Hosted invariants

Hosted startup must preserve:

- `DEMO_ONLY_MODE=true`;
- `REQUIRE_LICENSE=true`;
- PostgreSQL;
- HTTPS public base URL;
- strong independent admin, registration/bot and EA service secrets;
- versioned Alembic schema at the exact current head.

Provider/customer credentials are additional tenant/account credentials; do not reuse service secrets as provider/customer identity.

The hosted Provider Edition does **not** use the historical shared `SIGNAL_PROVIDER_INVITE_CODE` / `/provider <code>` flow.

## 3. Secrets

Start from `.env.hosted.example` and place real values only in the deployment secret store.

Never commit:

- database password;
- Telegram bot token;
- admin service secret;
- registration/bot service secret;
- EA service secret;
- provider API keys;
- customer EA licences;
- Anthropic/other extractor keys;
- backup recovery private identity.

Provider API keys and customer EA licences are returned only at issuance/rotation and are stored by SignalGate only in hashed/last-four form according to `docs/CREDENTIALS.md`.

## 4. Database

Do **not** initialise hosted PostgreSQL with `scripts/init_db.py` or application `create_all()`.

From `backend/`:

```bash
export DATABASE_URL='postgresql://...'
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
alembic -c alembic.ini check
```

Application startup independently fails closed if the hosted database is not at the exact migration head.

For an existing pre-Alembic database, follow `docs/DATABASE_MIGRATIONS.md`; never stamp a populated database without the isolated-restore baseline verification.

## 5. Build and deploy

Build from a reviewed candidate SHA.

The repository container is the reproducible hosted baseline. The sample staging Compose configuration keeps the application surface constrained and PostgreSQL separate.

Before routing provider traffic:

1. migrate database to head;
2. start backend/bot;
3. verify `/livez`;
4. verify `/readyz` performs the database round trip;
5. verify `/health` reports demo-only mode;
6. verify provider/feed pause controls;
7. verify protected metrics access;
8. run the accepted simulator/demo smoke path.

Do not use real-money accounts.

## 6. Provider onboarding

Use `docs/FIRST_PROVIDER_RUNBOOK.md`.

Current provider flow:

1. provision isolated organisation/provider/feed with `scripts/provision_provider.py` or equivalent authenticated admin workflow;
2. deliver the one-time provider credential privately;
3. provider logs into the Provider Portal and rotates the initial credential;
4. configure feed policy while paused;
5. generate a one-time feed-bound Telegram source token;
6. provider sends `/connectprovider <token>` from the intended source identity;
7. generate private subscriber feed invites;
8. subscriber explicitly accepts with its own `/join sgi_...`;
9. validate demo account/licence ownership;
10. run mandatory failure scenarios before opening the cohort.

Providers cannot directly attach subscribers behind their backs.

## 7. EA/customer boundary

Hosted EA calls use:

- server-held EA service credential; and
- the customer's one-time licence as the account identity credential.

Provider/customer credentials are sent in headers, not query strings.

A customer licence authenticates only the owning customer/account. Do not guess user ids, reuse licences across customers or ship a universal customer credential.

The EA remains demo-only and must refuse a real account.

## 8. Provider Telegram source

Hosted provider signal source is feed-bound.

Use `docs/PROVIDER_TELEGRAM_SOURCE.md`.

Do not configure a shared hosted provider API key or shared provider invite code in place of the one-time source binding flow.

## 9. Backup and restore

Do not deploy the old plaintext cron `pg_dump | gzip` recipe.

Hosted backups use:

```bash
export DATABASE_URL='postgresql://...'
export BACKUP_AGE_RECIPIENT='age1...'
bash scripts/backup_postgres.sh
```

The script encrypts with age, removes the plaintext temporary dump and writes a checksum.

Restore only into an isolated empty database using `scripts/restore_postgres.sh` and the separately held recovery identity.

See `docs/BACKUP_RESTORE.md`.

## 10. Observability

Current repository baseline provides:

- request correlation IDs;
- structured request logs that exclude query strings/headers/bodies;
- readiness/liveness;
- protected aggregate operational metrics;
- pre-production SLO/alert targets.

A provider beta still needs a real central log/metrics backend, alert routing, retention and on-call ownership. Do not claim measured SLO history until it exists.

See `docs/OBSERVABILITY.md`.

## 11. Before the first real provider

Use:

- `docs/BETA_ACCEPTANCE.md`;
- `docs/ACCEPTANCE_EVIDENCE_INDEX.md`;
- `docs/EXTERNAL_ACCEPTANCE_HANDOFF.md`;
- `docs/FIRST_PROVIDER_RUNBOOK.md`.

The controlled provider pilot remains demo-account only and explicit per-transaction authorisation remains required.

## 12. External gates

A correct deployment does not close:

- MetaEditor/demo acceptance;
- independent pentest/security review;
- UK regulatory/financial-promotion review;
- privacy/contract review;
- production-like recovery drill;
- measured SLO history;
- real-provider operating evidence.

Do not enable UK retail real-money or automatic-copy execution merely because hosted deployment works.
