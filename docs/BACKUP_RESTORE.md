# PostgreSQL Backup and Restore Drill

A backup is not considered real until a restore has been proven.

## Client/server compatibility

Run `pg_dump` with a client major version that is compatible with the PostgreSQL
server. CI deliberately uses PostgreSQL 16 with the Ubuntu runner's PostgreSQL 16
client so the smoke test exercises SignalGate's backup scripts rather than failing
on a client/server version mismatch. Production operations should pin a matching
client/container explicitly.

## Backup

Use a privileged operations environment with the database URL supplied as an
environment variable:

```bash
bash scripts/backup_postgres.sh
```

The script writes a timestamped custom-format `pg_dump` and SHA-256 checksum.
Store both in encrypted, access-controlled object storage with retention/versioning.

## Restore drill

Restore into an **empty isolated database**, never over production:

```bash
RESTORE_DATABASE_URL='postgresql://...' \
BACKUP_FILE='backups/signalgate-....dump' \
bash scripts/restore_postgres.sh
```

After restore:
1. run readiness/database connectivity;
2. prove the restored Alembic schema is current;
3. compare table counts and latest audit ids/timestamps with the backup receipt;
4. run read-only smoke tests;
5. record RTO/RPO and discrepancies;
6. destroy the isolated restore environment.

CI performs an ephemeral PostgreSQL migration-to-head → backup → checksum
verification → isolated restore → restored-schema check → sentinel-data
verification. That proves the current migrated schema and scripts can round-trip
database data.

G6 still remains failed until a production-like drill restores a retained,
encrypted backup into an isolated environment and records RTO/RPO, table/audit
comparisons, access controls, and any discrepancies.
