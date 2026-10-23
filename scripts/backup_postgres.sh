#!/usr/bin/env bash
# Logical backup of the production database. Run on a schedule from an operator machine or a Railway cron job.
# Requires DATABASE_URL (the connection string) and BACKUP_DIR. Keeps the newest BACKUP_KEEP dumps.
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL}"
: "${BACKUP_DIR:?set BACKUP_DIR (an off-platform location)}"
KEEP="${BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/mpd-$stamp.dump"

pg_dump --format=custom --no-owner --no-acl --dbname="$DATABASE_URL" --file="$out"
sha256sum "$out" > "$out.sha256"
echo "wrote $out"

# Retention: keep the newest $KEEP dumps (and their checksums).
ls -1t "$BACKUP_DIR"/mpd-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old" "$old.sha256"
  echo "pruned $old"
done
