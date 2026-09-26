.PHONY: build up down logs test-api test-web migrate smoke install start stop backup restore config test-config-redaction

# compose.yaml pins `name: decision-assistant`, which overrides Compose's
# normal directory-based project naming. Every test target below must pass
# an explicit -p override to this isolated project name, or it silently
# builds/runs against (and overwrites the image tags of) the user's real,
# already-deployed decision-assistant-* containers/images (see DB21).
TEST_PROJECT := decision-assistant-test

build:
	docker compose build

# Redacted `docker compose config`: the plain form prints resolved secret
# values (GEMINI_API_KEY, AUTH_JWT_SECRET, AUTH_BOOTSTRAP_PASSWORD,
# POSTGRES_PASSWORD, and any embedded connection-string password) straight to
# stdout. Use this target instead when sharing output in a terminal, ticket,
# CI log, or screen-share. See scripts/redact_config.awk: it also redacts
# multi-line block-scalar secrets and passwords containing a literal "@".
config:
	@docker compose config | awk -f scripts/redact_config.awk

# Regression fixture for scripts/redact_config.awk (fake secrets only). Run
# this before editing the redaction script to confirm you haven't regressed
# a case a checker previously found (see scripts/fixtures/redact_config/).
test-config-redaction:
	@scripts/test_redact_config.sh

up:
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

test-api:
	docker compose -p $(TEST_PROJECT) up -d db --wait
	API_BUILD_TARGET=test docker compose -p $(TEST_PROJECT) -f compose.yaml -f compose.test.yml build api
	API_BUILD_TARGET=test docker compose -p $(TEST_PROJECT) -f compose.yaml -f compose.test.yml run --rm api pytest
	docker compose -p $(TEST_PROJECT) down -v

test-web:
	WEB_BUILD_TARGET=build docker compose -p $(TEST_PROJECT) build web
	WEB_BUILD_TARGET=build docker compose -p $(TEST_PROJECT) run --rm --no-deps web npm test -- --run

migrate:
	docker compose run --rm api alembic upgrade head

smoke:
	bash scripts/smoke.sh

# --- quickstart.md Section 1 (install/start) and Section 5 (backup/restore) ---

install:
	docker compose pull
	docker compose build

start:
	docker compose up -d --wait

stop:
	docker compose down

BACKUP_DIR ?= backups

# Delegates to scripts/backup.sh (T035): a decision-assistant-backup-<UTC timestamp>.tar.gz
# containing both database.sql (pg_dump) and uploads.tar (uploads_data contents).
backup:
	scripts/backup.sh "$(BACKUP_DIR)"

# Usage: make restore -- <backup-file>
ifeq (restore,$(firstword $(MAKECMDGOALS)))
  RESTORE_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  $(eval $(RESTORE_ARGS):;@:)
endif

# Delegates to scripts/restore.sh (T036), the counterpart to scripts/backup.sh above.
restore:
	@test -n "$(RESTORE_ARGS)" || (echo "Usage: make restore -- <backup-file>" && exit 1)
	scripts/restore.sh "$(firstword $(filter-out --,$(RESTORE_ARGS)))"
