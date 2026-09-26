#!/usr/bin/env bash
# Reverses scripts/backup.sh: restores a database.sql (pg_dump --clean --if-exists) and
# uploads.tar (uploads_data contents) bundled in a decision-assistant-backup-*.tar.gz archive.
# Usage: scripts/restore.sh <backup-file>
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: scripts/restore.sh <backup-file>" >&2
  exit 1
fi

BACKUP_FILE="$1"
POSTGRES_USER="${POSTGRES_USER:-decision_assistant}"
POSTGRES_DB="${POSTGRES_DB:-decision_assistant}"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "Extracting $BACKUP_FILE..." >&2
tar -xzf "$BACKUP_FILE" -C "$WORKDIR" database.sql uploads.tar

echo "Restoring database..." >&2
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB" \
  < "$WORKDIR/database.sql"

echo "Restoring uploads..." >&2
docker compose exec -T api tar -xf - -C /workspace/uploads < "$WORKDIR/uploads.tar"

echo "Restore complete."
