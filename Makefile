.PHONY: build up down logs test-api test-web lint-api migrate smoke install start stop backup restore config test-config-redaction setup

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

# DB72(c): every test target ends with `down -v`, and that cleanup must run whether the tests
# pass or fail. As separate recipe lines a failing middle line skips it, leaving the isolated
# project's `api_logs`, `postgres_data` and `uploads_data` volumes behind on every red run. Each
# target is therefore one shell command whose last step cleans up and re-exits with the run's own
# status, so `make test-api`/`make test-web` still fail loudly.
test-api:
	docker compose -p $(TEST_PROJECT) up -d db --wait \
	 && API_BUILD_TARGET=test docker compose -p $(TEST_PROJECT) -f compose.yaml -f compose.test.yml build api \
	 && API_BUILD_TARGET=test docker compose -p $(TEST_PROJECT) -f compose.yaml -f compose.test.yml run --rm api pytest; \
	ret=$$?; docker compose -p $(TEST_PROJECT) down -v; exit $$ret

# DB69: this target starts no service of its own, but `-p $(TEST_PROJECT)` shares the isolated
# project with `test-api`, so whatever a previous run left behind (`api_logs`, `postgres_data`,
# `uploads_data`) has to be removed here too — otherwise the volumes accumulate on every run.
test-web:
	WEB_BUILD_TARGET=build docker compose -p $(TEST_PROJECT) build web \
	 && WEB_BUILD_TARGET=build docker compose -p $(TEST_PROJECT) run --rm --no-deps web npm test -- --run; \
	ret=$$?; docker compose -p $(TEST_PROJECT) down -v; exit $$ret

# T070/DB47 option (a): the backend linter. The pin lives in api/pyproject.toml's
# `dev` extra, which the `test` Dockerfile stage installs, so this runs the same
# ruff version the CI lint job installs. No database is needed, hence --no-deps.
lint-api:
	API_BUILD_TARGET=test docker compose -p $(TEST_PROJECT) -f compose.yaml -f compose.test.yml build api \
	 && API_BUILD_TARGET=test docker compose -p $(TEST_PROJECT) -f compose.yaml -f compose.test.yml run --rm --no-deps api ruff check src tests; \
	ret=$$?; docker compose -p $(TEST_PROJECT) down -v; exit $$ret

migrate:
	docker compose run --rm api alembic upgrade head

smoke:
	bash scripts/smoke.sh

# --- quickstart.md Section 1 (install/start) and Section 5 (backup/restore) ---

install:
	docker compose pull
	docker compose build

# First-run setup (US5/FR-013, T041): generates AUTH_JWT_SECRET, POSTGRES_PASSWORD and the
# DATABASE_URL that carries it into `.env`, then rotates the database role's password so an
# existing `postgres_data` volume — where Postgres ignores a changed POSTGRES_PASSWORD because
# initdb already ran — matches. Idempotent: it keeps real values unless called as
# `FORCE=1 make setup`, which rotates them. Never prints a secret value. See scripts/setup.sh.
setup:
	@FORCE="$(FORCE)" scripts/setup.sh

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

# T034/D8: host-side round trip for `backup`/`restore` above, in its own isolated
# project (the scripts call bare `docker compose`, so COMPOSE_PROJECT_NAME is what
# keeps this off the real stack). Asserts row counts and upload files match.
test-backup:
	TEST_PROJECT=$(TEST_PROJECT)-backup scripts/test_backup_restore.sh
