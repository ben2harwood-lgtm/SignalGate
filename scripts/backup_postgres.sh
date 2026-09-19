#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"

umask 077
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
plain="$(mktemp "backups/.signalgate-${stamp}.XXXXXX.dump")"
trap 'rm -f "$plain"' EXIT

pg_dump --format=custom --no-owner --no-acl --dbname="$DATABASE_URL" --file="$plain"

if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  command -v age >/dev/null 2>&1 || {
    echo "age is required for encrypted backups" >&2
    exit 2
  }
  file="backups/signalgate-${stamp}.dump.age"
  age --recipient "$BACKUP_AGE_RECIPIENT" --output "$file" "$plain"
  rm -f "$plain"
elif [[ "${BACKUP_ALLOW_PLAINTEXT:-false}" == "true" ]]; then
  file="backups/signalgate-${stamp}.dump"
  mv "$plain" "$file"
else
  echo "Refusing plaintext backup. Set BACKUP_AGE_RECIPIENT, or explicitly set BACKUP_ALLOW_PLAINTEXT=true for local/test use." >&2
  exit 2
fi

sha256sum "$file" > "$file.sha256"
printf 'backup=%s\nchecksum=%s\nencrypted=%s\n'   "$file" "$file.sha256" "$([[ "$file" == *.age ]] && echo true || echo false)"
