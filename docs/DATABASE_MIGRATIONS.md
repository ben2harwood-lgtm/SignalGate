# Database migrations

Hosted SignalGate schema is versioned with Alembic. Application startup must not
attempt to evolve PostgreSQL with SQLAlchemy `create_all()`.

## New hosted database

From `backend/`:

```bash
export DATABASE_URL='postgresql://...'
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
alembic -c alembic.ini check
```

Hosted application startup independently checks the Alembic revision and fails
closed unless the database is exactly at the single migration head. The
migration command must still be run explicitly; application startup never
applies schema changes.

## SQLAlchemy 2.1 PostgreSQL driver compatibility

Hosted SignalGate explicitly installs `psycopg2-binary` and its SQLAlchemy
application/Alembic engines select the `postgresql+psycopg2` dialect.
SQLAlchemy 2.1 otherwise defaults plain `postgresql://` URLs to `psycopg`
(psycopg3), which is **not** part of this deployment.

**Keep `DATABASE_URL` in the normal `postgresql://` form.** Do not change
the deployment secret, PostgreSQL command-line/backup scripts, or DSN to
`postgresql+psycopg2://`: the latter is SQLAlchemy-specific and not a
portable libpq DSN. The application and Alembic select the installed driver
only when constructing SQLAlchemy engines; `postgres://` aliases are also
normalised. Explicit SQLAlchemy driver schemes are left unchanged.

An ORM upgrade does not itself change the schema or authorise a production
migration/rollout. Prove actual PostgreSQL tests, full Alembic smoke,
encrypted backup/restore and deep-security scanning for the exact candidate
before deciding to deploy it.

## Adopting an existing pre-Alembic database

**Do not run the baseline migration over populated tables that already exist.**

1. Take and verify a backup.
2. Point `DATABASE_URL` at an isolated restored copy first.
3. Run the read-only baseline verifier from the repository root:

```bash
python scripts/verify_migration_baseline.py
```

4. If and only if verification passes, record the existing schema as the
baseline without changing it:

```bash
cd backend
alembic -c alembic.ini stamp 20260918_0001
alembic -c alembic.ini current
alembic -c alembic.ini check
```

5. Repeat against production only under an approved migration window after the
restore rehearsal succeeds.

The verifier requires the historical tables, columns, primary keys, selected
unique constraints **and all baseline approval/command/execution/performance
foreign keys**. Matching column names alone do not establish a safe baseline:
missing or cross-schema relationships now fail the check before any `alembic
stamp` instruction is printed. The PostgreSQL reflection explicitly ignores
`search_path` elision when identifying referenced schemas: a foreign target
must not look local merely because its schema is on the connection search path. This is still a read-only *structural preflight*,
not a data-integrity audit, type/nullability certification, or permission to
skip the isolated restore rehearsal and operator approval.

A failed baseline check is a hard stop, not permission to stamp anyway.

## New schema changes

Every ORM schema change must ship with a new migration. CI proves:

- upgrade from empty PostgreSQL to head;
- `alembic check` reports no model/schema drift;
- downgrade to base succeeds;
- re-upgrade to head succeeds;
- the baseline verifier passes.

Never edit an already-applied migration to make a later model change pass.
Create a new revision.

## Rollback

Application rollback and schema downgrade are separate decisions. Do not
downgrade a production database merely because application code is rolled back.
A downgrade must be shown safe for stored data and rehearsed first.
