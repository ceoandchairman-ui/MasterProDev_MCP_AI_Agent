#!/usr/bin/env bash
# Restore drill: restores the newest backup into a scratch database and checks that the core tables are populated.
# Never points at production. Requires SCRATCH_DATABASE_URL (a separate, empty database) and BACKUP_DIR.
set -euo pipefail

: "${SCRATCH_DATABASE_URL:?set SCRATCH_DATABASE_URL to an empty scratch database}"
: "${BACKUP_DIR:?set BACKUP_DIR}"

latest="$(ls -1t "$BACKUP_DIR"/mpd-*.dump | head -n 1)"
(cd "$BACKUP_DIR" && sha256sum -c "$(basename "$latest").sha256")

pg_restore --clean --if-exists --no-owner --no-acl --dbname="$SCRATCH_DATABASE_URL" "$latest"

for table in tenants users sessions; do
  count="$(psql "$SCRATCH_DATABASE_URL" -tAc "select count(*) from $table")"
  echo "$table: $count rows"
done
echo "restore drill finished for $latest; record the elapsed time against the RTO target"
