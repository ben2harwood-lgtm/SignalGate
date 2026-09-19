#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="backups/signalgate-${stamp}.dump"
pg_dump --format=custom --no-owner --no-acl --dbname="$DATABASE_URL" --file="$file"
sha256sum "$file" > "$file.sha256"
printf 'backup=%s\nchecksum=%s\n' "$file" "$file.sha256"
