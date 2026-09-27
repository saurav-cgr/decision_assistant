#!/usr/bin/env bash
# First-run setup (US5/FR-013, T041): generate the secrets a fresh install must not share.
#
# Why this is a host script wrapping a container module: the api container receives every setting as
# an explicit `environment:` entry that Compose substitutes from the host repo-root `.env`, so only
# the host can change them; a container cannot write that file, and the only mount that would let it
# is the repo root, which the no-source-bind-mount rule forbids (loop debt DB58). All the decision
# logic therefore lives in `decision_assistant.setup.bootstrap` (unit-tested by T040) and this script
# only moves text between the host file and that module.
#
# What it does, in order:
#   1. creates .env from .env.example when absent (mode 600)
#   2. pipes .env through the module, which fills (or, with FORCE=1, rotates) the three keys
#   3. replaces .env atomically, after asserting the module produced all three keys
#   4. starts `db` and rotates the role's password, so an existing `postgres_data` volume — where
#      Postgres ignores a changed POSTGRES_PASSWORD because initdb already ran — matches the new one
#
# It never prints a secret value. `make setup` / `FORCE=1 make setup`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-.env}"
EXAMPLE_FILE=".env.example"
FORCE="${FORCE:-0}"
API_IMAGE="decision-assistant-api:latest" # compose.yaml pins `name: decision-assistant` (DB21)
SETUP_MODULE="decision_assistant.setup.bootstrap"

log() { printf 'setup: %s\n' "$*"; }
die() {
  printf 'setup: error: %s\n' "$*" >&2
  exit 1
}

# Last occurrence wins, matching how dotenv/Compose read the file.
env_value() {
  sed -n "s/^$1=//p" "$2" | tail -n 1
}

[ -f "$EXAMPLE_FILE" ] || die "$EXAMPLE_FILE is missing; run this from the repository root"

if [ ! -f "$ENV_FILE" ]; then
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  log "created $ENV_FILE from $EXAMPLE_FILE"
fi

log "building the api image (needed for the setup module)"
docker compose build api >/dev/null

if [ "$FORCE" != "1" ]; then
  status_json="$(docker compose run --rm -T api python -m "$SETUP_MODULE" status <"$ENV_FILE")"
  case "$status_json" in
  *'"configured": true'*)
    log "$ENV_FILE already holds generated secrets; nothing to do"
    log "re-run with FORCE=1 make setup to rotate them (this changes the database password)"
    exit 0
    ;;
  esac
fi

env_tmp="$(mktemp "${TMPDIR:-/tmp}/decision-assistant-env.XXXXXX")"
chmod 600 "$env_tmp"
trap 'rm -f "$env_tmp"' EXIT

if [ "$FORCE" = "1" ]; then
  log "rotating the generated secrets in $ENV_FILE"
  docker compose run --rm -T api python -m "$SETUP_MODULE" env --force <"$ENV_FILE" >"$env_tmp"
else
  log "generating secrets into $ENV_FILE"
  docker compose run --rm -T api python -m "$SETUP_MODULE" env <"$ENV_FILE" >"$env_tmp"
fi

# Assert before replacing anything: a partial or corrupted capture must never become the live .env.
for key in POSTGRES_PASSWORD AUTH_JWT_SECRET DATABASE_URL; do
  [ -n "$(env_value "$key" "$env_tmp")" ] ||
    die "$ENV_FILE was left unchanged: the generated configuration has no $key"
done

mv "$env_tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

postgres_user="$(env_value POSTGRES_USER "$ENV_FILE")"
postgres_user="${postgres_user:-decision_assistant}"
postgres_db="$(env_value POSTGRES_DB "$ENV_FILE")"
postgres_db="${postgres_db:-decision_assistant}"
new_password="$(env_value POSTGRES_PASSWORD "$ENV_FILE")"

# The one place this script builds SQL. AGENTS.md forbids interpolating untrusted input, so the role
# name must be a plain identifier and the password must be the generator's hex form — which needs no
# quoting or escaping in a SQL literal. Both are asserted rather than assumed, so a future change to
# the generator shape fails here instead of producing broken or injectable SQL.
if [[ ! "$postgres_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  die "POSTGRES_USER is not a plain identifier; refusing to build SQL from it"
fi
if [[ ! "$new_password" =~ ^[0-9a-f]{64}$ ]]; then
  die "POSTGRES_PASSWORD is not the expected hex form; refusing to build SQL from it"
fi

log "starting the database so its role can be rotated"
docker compose up -d db --wait >/dev/null

printf 'ALTER ROLE "%s" WITH PASSWORD '"'"'%s'"'"';\n' "$postgres_user" "$new_password" |
  docker compose exec -T db psql -U "$postgres_user" -d "$postgres_db" -v ON_ERROR_STOP=1 >/dev/null

log "wrote $ENV_FILE (mode 600) with POSTGRES_PASSWORD, AUTH_JWT_SECRET and DATABASE_URL"
log "aligned role '$postgres_user' in the running database with that password"
log "next: make start"
