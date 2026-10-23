#!/usr/bin/env bash
set -euo pipefail
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"

# A .sha256 manifest may name another file: bind integrity to this exact target.
# Capture the hash command status: process substitution alone can hide read errors.
if ! actual_checksum_record="$(sha256sum "$BACKUP_FILE")"; then
  echo "Unable to hash requested BACKUP_FILE; refusing restore" >&2
  exit 2
fi
if ! cmp -s <(printf '%s\\n' "$actual_checksum_record") "$BACKUP_FILE.sha256"; then
  echo "Checksum manifest does not match requested BACKUP_FILE; refusing restore" >&2
  exit 2
fi

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
