#!/usr/bin/env bash
set -euo pipefail
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"
sha256sum --check "$BACKUP_FILE.sha256"
pg_restore --exit-on-error --no-owner --no-acl --clean --if-exists \
  --dbname="$RESTORE_DATABASE_URL" "$BACKUP_FILE"
printf 'restore_completed=%s\n' "$BACKUP_FILE"
