# PostgreSQL Backup and Restore Drill

A backup is not considered real until encryption, checksum verification and an isolated restore have been proven.

## Encryption model

Hosted backups fail closed unless `BACKUP_AGE_RECIPIENT` is set. The backup host needs only the age **public recipient**; the private identity should be held separately for recovery.

Generate an operations identity on a secure machine:

```bash
age-keygen -o signalgate-backup-age-key.txt
age-keygen -y signalgate-backup-age-key.txt
```

Store the private identity in the approved recovery secret store. Configure only the printed `age1...` public recipient on the backup host.

## Backup

```bash
export DATABASE_URL='postgresql://...'
export BACKUP_AGE_RECIPIENT='age1...'
bash scripts/backup_postgres.sh
```

The script:

1. creates a restrictive-permission temporary custom-format `pg_dump`;
2. encrypts it with age;
3. removes the plaintext temporary dump;
4. writes a SHA-256 checksum of the encrypted artifact.

Expected artifact: `backups/signalgate-<timestamp>.dump.age` plus `.sha256`.

Plaintext backup is refused unless `BACKUP_ALLOW_PLAINTEXT=true` is explicitly set. That escape hatch is for local/test use only.

Store encrypted artifacts in access-controlled object storage with versioning/retention and separate deletion authority where practical.

## Restore drill

Restore into an **empty isolated database**, never over production:

```bash
export RESTORE_DATABASE_URL='postgresql://...'
export BACKUP_FILE='backups/signalgate-....dump.age'
export BACKUP_AGE_IDENTITY_FILE='/secure/path/signalgate-backup-age-key.txt'
bash scripts/restore_postgres.sh
```

The restore script verifies the encrypted artifact checksum before decrypting to a restrictive temporary file, restores with `pg_restore --exit-on-error`, then removes the temporary plaintext.

Plaintext restore is refused unless `BACKUP_ALLOW_PLAINTEXT_RESTORE=true` is explicitly set.

## Restore evidence

After restore:

1. run readiness and read-only application smoke tests;
2. compare table counts and latest audit ids/timestamps with the backup receipt;
3. verify migration head;
4. record RTO/RPO and discrepancies;
5. record who performed and reviewed the drill;
6. destroy the isolated restore environment and any temporary plaintext.

CI generates an ephemeral age key, performs PostgreSQL migration-to-head, writes sentinel data, creates an **encrypted** backup, verifies its checksum, restores it into an isolated database and proves the sentinel survived.

That proves the scripts and encryption round-trip. G6 still requires a scheduled production-like drill against a retained backup with recorded RTO/RPO, access controls and reviewer sign-off.


## Alert integration

Backup failure, checksum failure and restore-drill failure are urgent alert conditions in `docs/OBSERVABILITY.md`. When a central monitoring backend is connected, retain the alert-delivery receipt alongside each scheduled restore drill.
