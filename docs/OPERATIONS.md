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
- All API secrets are injected from the deployment secret store; they are never
  committed to the repository.

## Probes

- `GET /livez`: process liveness only.
- `GET /readyz`: returns ready only after a database round-trip.
- `GET /health`: application state summary, including demo-only/admin pause.

Load balancers should use `/readyz`; process supervisors may use `/livez`.

## Deploy

1. Generate unique 32+ character EA/admin/provider/registration secrets.
2. Set a strong PostgreSQL password outside the repository.
3. Set `BACKEND_BASE_URL` to the public **HTTPS** origin.
4. Build the image from a reviewed commit.
5. Run schema migration gate before application rollout once Alembic migrations
   land. Until then, this release is not production-migration-ready.
6. Start one instance, verify readiness, then expand.
7. Run the simulator smoke flow only; do not use real-money trading during
   hardening.

## Release evidence still required

- versioned/reversible database migrations;
- central log aggregation and alerts;
- production-like retained-backup restore drill with measured RTO/RPO (CI now
  proves the backup/restore scripts round-trip data on ephemeral PostgreSQL);
- SLO/error budget;
- credential rotation drill;
- independent penetration test;
- production rollback exercise.

Do not mark G6 complete until those have actual receipts.
