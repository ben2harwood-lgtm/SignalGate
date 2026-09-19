#!/usr/bin/env bash
set -euo pipefail
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"

sha256sum --check "$BACKUP_FILE.sha256"

restore_file="$BACKUP_FILE"
temp=""
cleanup() {
  if [[ -n "$temp" ]]; then rm -f "$temp"; fi
}
trap cleanup EXIT

if [[ "$BACKUP_FILE" == *.age ]]; then
  : "${BACKUP_AGE_IDENTITY_FILE:?BACKUP_AGE_IDENTITY_FILE is required for encrypted restore}"
  command -v age >/dev/null 2>&1 || {
    echo "age is required for encrypted restore" >&2
    exit 2
  }
  temp="$(mktemp)"
  chmod 600 "$temp"
  age --decrypt --identity "$BACKUP_AGE_IDENTITY_FILE" --output "$temp" "$BACKUP_FILE"
  restore_file="$temp"
elif [[ "${BACKUP_ALLOW_PLAINTEXT_RESTORE:-false}" != "true" ]]; then
  echo "Refusing plaintext restore. Set BACKUP_ALLOW_PLAINTEXT_RESTORE=true only for explicit local/test recovery." >&2
  exit 2
fi

pg_restore --exit-on-error --no-owner --no-acl --clean --if-exists   --dbname="$RESTORE_DATABASE_URL" "$restore_file"
printf 'restore_completed=%s\nencrypted=%s\n'   "$BACKUP_FILE" "$([[ "$BACKUP_FILE" == *.age ]] && echo true || echo false)"
