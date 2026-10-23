#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"

umask 077
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
plain="$(mktemp "backups/.signalgate-${stamp}.XXXXXX.dump")"
file=""
checksum=""
completed=false

cleanup() {
  rm -f -- "$plain"
  if [[ "$completed" != true ]]; then
    if [[ -n "$file" ]]; then rm -f -- "$file"; fi
    if [[ -n "$checksum" ]]; then rm -f -- "$checksum"; fi
  fi
}
trap cleanup EXIT

pg_dump --format=custom --no-owner --no-acl --dbname="$DATABASE_URL" --file="$plain"

if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  command -v age >/dev/null 2>&1 || {
    echo "age is required for encrypted backups" >&2
    exit 2
  }
  # mktemp atomically reserves a unique name; no backup from the same second
  # can overwrite an earlier complete artifact. age writes ciphertext to stdout.
  file="$(mktemp "backups/signalgate-${stamp}.XXXXXXXX.dump.age")"
  age --recipient "$BACKUP_AGE_RECIPIENT" "$plain" > "$file"
elif [[ "${BACKUP_ALLOW_PLAINTEXT:-false}" == "true" ]]; then
  # Explicit local/test escape hatch only. Reserve uniquely here as well.
  file="$(mktemp "backups/signalgate-${stamp}.XXXXXXXX.dump")"
  mv -- "$plain" "$file"
else
  echo "Refusing plaintext backup. Set BACKUP_AGE_RECIPIENT, or explicitly set BACKUP_ALLOW_PLAINTEXT=true for local/test use." >&2
  exit 2
fi

if [[ ! -s "$file" ]]; then
  echo "Backup artifact missing or empty; refusing success" >&2
  exit 2
fi
checksum="$file.sha256"
sha256sum "$file" > "$checksum"
completed=true
printf 'backup=%s\nchecksum=%s\nencrypted=%s\n' \
  "$file" "$checksum" "$([[ "$file" == *.age ]] && echo true || echo false)"
