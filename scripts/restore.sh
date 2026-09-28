#!/usr/bin/env bash
# Reverses scripts/backup.sh: restores a database.sql (pg_dump --clean --if-exists) and
# uploads.tar (uploads_data contents) bundled in a decision-assistant-backup-*.tar.gz archive.
# Usage: scripts/restore.sh <backup-file>
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: scripts/restore.sh <backup-file>" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_FILE="$1"

# DB52: the database name/role can be customized in `.env`, which is what Compose reads for the
# `db` service, so these scripts read the same file instead of trusting the shell environment and
# their defaults. Only these two names are read; the file's secrets are never expanded or printed.
env_value() {
  local key="$1" value
  [ -f "$REPO_ROOT/.env" ] || return 0
  value="$(sed -n "s/^[[:space:]]*${key}=//p" "$REPO_ROOT/.env" | tail -n 1)"
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  printf '%s' "$value"
}

POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_USER="${POSTGRES_USER:-decision_assistant}"
POSTGRES_DB="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
POSTGRES_DB="${POSTGRES_DB:-decision_assistant}"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "Extracting $BACKUP_FILE..." >&2
tar -xzf "$BACKUP_FILE" -C "$WORKDIR" database.sql uploads.tar

# DB52: extract over an empty directory, so the volume ends up matching the backup exactly.
# Without this, files uploaded after the backup survive and the restore is additive.
echo "Clearing the uploads directory..." >&2
docker compose exec -T api sh -lc 'find /workspace/uploads -mindepth 1 -delete'

echo "Restoring uploads..." >&2
docker compose exec -T api tar -xf - -C /workspace/uploads < "$WORKDIR/uploads.tar"

echo "Restoring database..." >&2
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB" \
  < "$WORKDIR/database.sql"

# DB51: the dump drops and recreates tables while the API still holds pooled asyncpg connections,
# so their cached statement plans and type OIDs are stale and the first request after the restore
# can fail with a 500. Recreating the container drops the pool. Restart only when it is running, so
# a restore against a stopped stack stays a data-only operation.
if [ -n "$(docker compose ps -q api 2>/dev/null)" ]; then
  echo "Restarting api to drop stale connections..." >&2
  docker compose restart api >&2
  # DB70: `restart` returns as soon as the container is started, not when it is serving, so without
  # this wait this script printed "Restore complete." while the API could still refuse connections.
  # `up -d --wait` does not recreate an unchanged container — the restart above is what drops the
  # stale pool — it just waits for the healthcheck to pass.
  echo "Waiting for the api to report healthy..." >&2
  docker compose up -d api --wait >&2
fi

echo "Restore complete."
