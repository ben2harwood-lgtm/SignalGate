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

Expected artifact: `backups/signalgate-<timestamp>.<unique-random-suffix>.dump.age` plus a matching `.sha256` manifest. Names are reserved uniquely, even for simultaneous backups in the same second; keep the complete filename returned by `backup=` when choosing `BACKUP_FILE` for a restore.

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

The restore script stages a regular, non-symlinked backup into an owner-only temporary snapshot and verifies **that snapshot** against the exact requested backup filename and digest. Both decrypt and `pg_restore` consume only the verified snapshot; a modified source file, stream, symlink or extra manifest record fails closed. Ordinary backup filenames (including spaces) are supported; paths requiring GNU checksum backslash/newline escaping are refused. Temporary storage must fit an additional copy of the encrypted artifact and, where applicable, the decrypted dump; clean exit removes both. A SHA-256 checksum detects accidental mismatch; it is not a signature or proof of authenticity.

**Isolated destination safeguard:** after checking the backup, the script uses a read-only `psql` system-catalogue query to refuse any target containing user relations (including ordinary tables, sequences or views). Connection errors and unexpected query output fail closed; an exact match between `DATABASE_URL` and `RESTORE_DATABASE_URL` also refuses restoration. It never passes `--clean` or `--if-exists` to `pg_restore`, so the drill command does not deliberately drop existing objects. `psql` must be installed alongside `pg_restore`. This is defence in depth, **not** proof that an operator-selected DSN is isolated or a substitute for verifying the target before running it. Nonempty database recovery needs a separately reviewed procedure; do not run this drill script against production.

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
