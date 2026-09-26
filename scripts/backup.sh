#!/usr/bin/env bash
# Produces decision-assistant-backup-<UTC timestamp>.tar.gz containing a pg_dump of the db
# service and a tar of the uploads_data volume contents, written to a host directory outside
# any Docker volume. Usage: scripts/backup.sh [destination-dir]
set -euo pipefail

DEST_DIR="${1:-backups}"
POSTGRES_USER="${POSTGRES_USER:-decision_assistant}"
POSTGRES_DB="${POSTGRES_DB:-decision_assistant}"

mkdir -p "$DEST_DIR"
DEST_DIR="$(cd "$DEST_DIR" && pwd)"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE_NAME="decision-assistant-backup-${TIMESTAMP}.tar.gz"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "Dumping database..." >&2
docker compose exec -T db pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" \
  > "$WORKDIR/database.sql"

echo "Archiving uploads..." >&2
docker compose exec -T api tar -cf - -C /workspace/uploads . > "$WORKDIR/uploads.tar"

echo "Writing $DEST_DIR/$ARCHIVE_NAME..." >&2
tar -czf "$DEST_DIR/$ARCHIVE_NAME" -C "$WORKDIR" database.sql uploads.tar

echo "$DEST_DIR/$ARCHIVE_NAME"
