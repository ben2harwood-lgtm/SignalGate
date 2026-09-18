# PostgreSQL Backup and Restore Drill

A backup is not considered real until a restore has been proven.

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
1. run `SELECT 1`/readiness;
2. compare table counts and latest audit ids/timestamps with the backup receipt;
3. run read-only smoke tests;
4. record RTO/RPO and discrepancies;
5. destroy the isolated restore environment.

G6 remains failed until a dated restore drill has actually succeeded.
