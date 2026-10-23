#!/usr/bin/env bash
set -euo pipefail
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"

# A restore must consume the exact bytes checked against the manifest.
# Reject nonregular or symlinked inputs and unsupported filename escapes.
if [[ ! -f "$BACKUP_FILE" || -L "$BACKUP_FILE" || "$BACKUP_FILE" == *\\* || "$BACKUP_FILE" == *$'\n'* ]]; then
  echo "BACKUP_FILE must be a regular nonsymlinked file with a simple filename; refusing restore" >&2
  exit 2
fi
umask 077
verified_backup="$(mktemp)"
temp=""
cleanup() {
  if [[ -n "$temp" ]]; then rm -f "$temp"; fi
  if [[ -n "$verified_backup" ]]; then rm -f "$verified_backup"; fi
}
trap cleanup EXIT
# Stage first, hash the private snapshot, and restore only that snapshot.
if ! cat -- "$BACKUP_FILE" > "$verified_backup"; then
  echo "Unable to stage BACKUP_FILE; refusing restore" >&2
  exit 2
fi
if ! digest_record="$(sha256sum "$verified_backup")"; then
  echo "Unable to hash staged BACKUP_FILE; refusing restore" >&2
  exit 2
fi
digest="${digest_record%% *}"
if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Unexpected SHA-256 digest format; refusing restore" >&2
  exit 2
fi
if ! cmp -s <(printf '%s  %s\n' "$digest" "$BACKUP_FILE") "$BACKUP_FILE.sha256"; then
  echo "Checksum manifest does not match staged BACKUP_FILE; refusing restore" >&2
  exit 2
fi
restore_file="$verified_backup"

if [[ "$BACKUP_FILE" == *.age ]]; then
  : "${BACKUP_AGE_IDENTITY_FILE:?BACKUP_AGE_IDENTITY_FILE is required for encrypted restore}"
  command -v age >/dev/null 2>&1 || {
    echo "age is required for encrypted restore" >&2
    exit 2
  }
  temp="$(mktemp)"
  chmod 600 "$temp"
  age --decrypt --identity "$BACKUP_AGE_IDENTITY_FILE" --output "$temp" "$verified_backup"
  restore_file="$temp"
elif [[ "${BACKUP_ALLOW_PLAINTEXT_RESTORE:-false}" != "true" ]]; then
  echo "Refusing plaintext restore. Set BACKUP_ALLOW_PLAINTEXT_RESTORE=true only for explicit local/test recovery." >&2
  exit 2
fi

pg_restore --exit-on-error --no-owner --no-acl --clean --if-exists   --dbname="$RESTORE_DATABASE_URL" "$restore_file"
printf 'restore_completed=%s\nencrypted=%s\n'   "$BACKUP_FILE" "$([[ "$BACKUP_FILE" == *.age ]] && echo true || echo false)"
