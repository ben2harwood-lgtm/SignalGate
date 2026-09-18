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

Only start the hosted application after the migration command succeeds.

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
