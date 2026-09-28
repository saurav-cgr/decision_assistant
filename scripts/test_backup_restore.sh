#!/usr/bin/env bash
# Host-side round trip for `make backup` / `make restore` (T034's other half; D8).
#
# `api/tests/integration/test_backup_restore.py` covers everything below the
# scripts — a real pg_dump through `create_pre_migration_backup`, the archive
# layout, and the psql restore. What it cannot cover is the scripts themselves,
# because `scripts/backup.sh` and `scripts/restore.sh` shell out to
# `docker compose exec`, which the api container cannot reach (DB22). This test
# runs on the host, the way the documented `make backup` / `make restore` flow
# does, and asserts the row and file counts that quickstart.md Section 5 asks
# the operator to confirm.
#
# Isolation: `compose.yaml` pins `name: decision-assistant`, so a bare
# `docker compose` here would target the real dev stack. Every command below
# inherits COMPOSE_PROJECT_NAME, which takes precedence over that name and is
# what keeps this test off the live project (DB21, DB46).
#
# Usage: scripts/test_backup_restore.sh [project-name]
set -euo pipefail

PROJECT="${1:-${TEST_PROJECT:-decision-assistant-backup-test}}"
export COMPOSE_PROJECT_NAME="$PROJECT"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

POSTGRES_USER="${POSTGRES_USER:-decision_assistant}"
POSTGRES_DB="${POSTGRES_DB:-decision_assistant}"
WORKSPACE_ID="11111111-1111-4111-8111-111111111111"
DECISION_ID="22222222-2222-4222-8222-222222222222"
UPLOAD_FILE="test-backup-restore.txt"
UPLOAD_FILE_BODY="host-side backup/restore test"
STRAY_FILE="stray-after-backup.txt"

# DB51/DB69: the assertion for the stale-connection bug needs a request that touches a table the
# restore drops and recreates, and it has to be prepared on a pooled connection *before* the backup.
# `/health` is not that request: it runs `SELECT 1`, which references no table and no custom type, so
# it passes whether or not the fix is present — and retrying it re-warms the pool and hides the bug.
PROBE_PATH="/api/v1/setup/status"

WORKDIR="$(mktemp -d)"
ARCHIVE=""

# Two compose-level variables keep this run out of the way of a live stack:
# - BACKUP_DIR: the api service bind-mounts `${BACKUP_DIR:-./backups}`, and a
#   fresh database means the startup path takes a pre-migration backup — that
#   archive belongs in this test's temp dir, not the repo's `./backups`.
# - API_PORT: the default 8000 may already be taken by a running dev stack.
export BACKUP_DIR="$WORKDIR/backups"
export API_PORT="${API_PORT:-18099}"
mkdir -p "$BACKUP_DIR"

cleanup() {
  rm -rf "$WORKDIR"
  docker compose -p "$PROJECT" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

psql_run() {
  docker compose -p "$PROJECT" exec -T db \
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB" "$@"
}

counts() {
  psql_run -tAc "select
    (select count(*) from workspaces),
    (select count(*) from decisions)"
}

# DB69: the api container's own pooled backends. `pid <> pg_backend_pid()` drops this psql
# session, and `client backend` keeps out Postgres's internal processes, so what is left is the
# API's pool — which is the thing DB51 is about. A restore that drops and recreates the tables
# without dropping that pool leaves the same backends connected with stale cached plans.
api_backend_pids() {
  psql_run -tAc "select pid from pg_stat_activity
                 where datname = current_database()
                   and pid <> pg_backend_pid()
                   and backend_type = 'client backend'
                 order by pid"
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "==> Starting isolated project '$PROJECT' (db + api)"
# Build first, deliberately: `up` only builds when the image is missing, so a cached
# `$PROJECT-api` from an earlier run would be tested instead of the current source. That is not
# hypothetical — a 25-hour-old image made this script fail on a startup check the source no longer
# has, which reads as a product failure. `make test-api`/`test-web` build for the same reason.
docker compose -p "$PROJECT" build api >/dev/null
docker compose -p "$PROJECT" up -d db api --wait >/dev/null

# DB69: warm the pool before the backup. The statement behind this request is prepared on a pooled
# connection now, so restoring without dropping that pool leaves a stale plan behind for the probe
# at the end of this script to find. Without this step the probe would be vacuous — the checker's
# V160 mutant (restore.sh's restart removed) passed the old version of this file.
echo "==> Warming the api connection pool (DB51/DB69)"
WARM_CODE=""
for _ in $(seq 1 30); do
  WARM_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${API_PORT}${PROBE_PATH}" || true)"
  [ "$WARM_CODE" = "200" ] && break
  sleep 1
done
[ "$WARM_CODE" = "200" ] \
  || fail "GET ${PROBE_PATH} before the backup returned '$WARM_CODE', not 200"

# DB69: snapshot the pooled backends the warm-up just created. Recording this *before* the backup is
# what makes the assertion after the restore mean something.
BACKEND_PIDS_BEFORE="$(api_backend_pids)"
[ -n "$BACKEND_PIDS_BEFORE" ] \
  || fail "the warm-up left no pooled connection behind, so the DB51 assertion below proves nothing"
echo "    pooled backends before: $(echo "$BACKEND_PIDS_BEFORE" | tr '\n' ' ')"

echo "==> Seeding one workspace, one decision, and one upload file"
psql_run <<SQL >/dev/null
insert into workspaces (id, name) values ('$WORKSPACE_ID', 'backup-restore-test')
  on conflict (id) do nothing;
insert into decisions (id, workspace_id, statement, status, provenance, review_state)
  values ('$DECISION_ID', '$WORKSPACE_ID', 'Backup/restore round trip.', 'active',
          'extracted', 'supported')
  on conflict (id) do nothing;
SQL
docker compose -p "$PROJECT" exec -T api \
  sh -lc "printf '%s\n' '$UPLOAD_FILE_BODY' > /workspace/uploads/$UPLOAD_FILE"

BEFORE_COUNTS="$(counts)"
[ -n "$BEFORE_COUNTS" ] || fail "could not read row counts before the backup"
echo "    rows before: $(echo "$BEFORE_COUNTS" | tr '\n' ' ')"

echo "==> scripts/backup.sh"
ARCHIVE="$(scripts/backup.sh "$WORKDIR")"
[ -f "$ARCHIVE" ] || fail "backup reported '$ARCHIVE' but no archive exists"
echo "    archive: $(basename "$ARCHIVE")"

echo "==> Wiping the seeded rows and the upload file"
psql_run -c "delete from workspaces where id = '$WORKSPACE_ID'" >/dev/null
docker compose -p "$PROJECT" exec -T api rm -f "/workspace/uploads/$UPLOAD_FILE"
# DB52: a file that arrives *after* the backup must not survive the restore — the uploads volume
# has to end up matching the archive, not a superset of it.
docker compose -p "$PROJECT" exec -T api \
  sh -lc "printf '%s\n' stray > /workspace/uploads/$STRAY_FILE"

AFTER_WIPE_COUNTS="$(counts)"
[ "$AFTER_WIPE_COUNTS" != "$BEFORE_COUNTS" ] \
  || fail "the wipe did not change the row counts, so the restore below proves nothing"

echo "==> scripts/restore.sh"
scripts/restore.sh "$ARCHIVE" >/dev/null

RESTORED_COUNTS="$(counts)"
[ "$RESTORED_COUNTS" = "$BEFORE_COUNTS" ] \
  || fail "row counts differ after restore: before='$BEFORE_COUNTS' after='$RESTORED_COUNTS'"

RESTORED_FILE="$(docker compose -p "$PROJECT" exec -T api \
  cat "/workspace/uploads/$UPLOAD_FILE")"
[ "$RESTORED_FILE" = "$UPLOAD_FILE_BODY" ] \
  || fail "uploaded file content differs after restore: '$RESTORED_FILE'"

if docker compose -p "$PROJECT" exec -T api test -e "/workspace/uploads/$STRAY_FILE"; then
  fail "$STRAY_FILE was uploaded after the backup but survived the restore (DB52)"
fi

# DB51/DB69: every backend the warm-up created must be gone. This is the assertion that actually
# discriminates: with the restart removed the api keeps the very same `pg_stat_activity` pids, which
# is precisely the stale-pool condition DB51 describes. Verified by running the V160 mutant
# (restart removed) against this file: it fails here, and the behavioural probe below did not
# notice on its own.
BACKEND_PIDS_AFTER="$(api_backend_pids)"
SURVIVOR=""
for pid in $BACKEND_PIDS_BEFORE; do
  if echo "$BACKEND_PIDS_AFTER" | grep -qw "$pid"; then
    SURVIVOR="$pid"
    break
  fi
done
[ -z "$SURVIVOR" ] \
  || fail "the restore left api backend pid $SURVIVOR connected, so the stale pool DB51 is about was never dropped"

# The symptom check, and the part the debt row asked for: one single-attempt typed request after the
# api is healthy again. It is kept as a regression check of the user-visible failure, but on its own
# it is not the discriminator — see the comment above.
echo "==> Proving the first typed request after the restore succeeds (DB51)"
PROBE_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${API_PORT}${PROBE_PATH}" || true)"
[ "$PROBE_CODE" != "000" ] \
  || fail "the API did not accept a connection on port $API_PORT after the restore"
[ "$PROBE_CODE" = "200" ] \
  || fail "the first ${PROBE_PATH} request after the restore returned '$PROBE_CODE', not 200 (DB51)"

echo "PASS: rows and uploads match before backup and after restore"
