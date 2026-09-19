# Production Operations Baseline

This is an **operations baseline**, not evidence that production release gates
have passed.

## Deployment shape

- TLS terminates at the hosting platform/reverse proxy.
- Only the proxy exposes the public backend; the sample Compose file binds the
  backend to loopback.
- PostgreSQL is the hosted source of truth.
- `REQUIRE_LICENSE=true` and `DEMO_ONLY_MODE=true` remain mandatory during
  the hardening release.
- EA, admin and registration secrets are injected from the deployment secret
  store; they are never committed to the repository.
- Provider credentials are issued per provider organisation, stored only as
  hashes by SignalGate and kept in the provider integration's secret store.

## Probes

- `GET /livez`: process liveness only.
- `GET /readyz`: returns ready only after a database round-trip.
- `GET /health`: application state summary, including demo-only/admin pause.

Load balancers should use `/readyz`; process supervisors may use `/livez`.

## Deploy

1. Generate unique 32+ character EA/admin/registration platform secrets.
2. Provision provider credentials through the admin provisioning API; do not
   create one shared hosted provider key.
3. Set a strong PostgreSQL password outside the repository.
4. Set `BACKEND_BASE_URL` to the public **HTTPS** origin.
5. Build the image from a reviewed commit.
6. Before application rollout run:
   `cd backend && alembic -c alembic.ini upgrade head && alembic -c alembic.ini check`.
   Hosted startup also refuses a stale/non-current migration state.
7. Start one instance, verify readiness, then expand.
8. Run simulator/demo-account smoke flows only; do not use real-money trading
   during hardening.

## Evidence already automated

- backend regression tests and Python compile;
- dependency vulnerability audit;
- Bandit medium/high static-security scan;
- PostgreSQL migrate-to-head, schema-drift check, historical-baseline check,
  stale-schema rejection and re-upgrade;
- non-root hosted container build;
- ephemeral PostgreSQL backup/checksum/isolated-restore/sentinel verification.

## Release evidence still required

- central structured log aggregation and alerts;
- production-like retained-backup restore drill with measured RTO/RPO;
- SLO/error-budget evidence;
- provider/platform credential rotation drill;
- independent penetration test and remediation;
- production rollback exercise;
- independent release review.

Do not mark G6 complete until those have actual receipts.
