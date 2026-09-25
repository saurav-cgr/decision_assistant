.PHONY: build up down logs test-api test-web migrate smoke install start stop backup restore config

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

up:
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

test-api:
	docker compose up -d db --wait
	API_BUILD_TARGET=test docker compose -f compose.yaml -f compose.test.yml build api
	API_BUILD_TARGET=test docker compose -f compose.yaml -f compose.test.yml run --rm api pytest

test-web:
	docker compose run --rm web npm test -- --run

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

backup:
	mkdir -p $(BACKUP_DIR)
	docker compose exec -T db pg_dump --clean --if-exists -U "$${POSTGRES_USER:-decision_assistant}" "$${POSTGRES_DB:-decision_assistant}" \
		> "$(BACKUP_DIR)/backup-$$(date +%Y%m%d%H%M%S).sql"

# Usage: make restore -- <backup-file>
ifeq (restore,$(firstword $(MAKECMDGOALS)))
  RESTORE_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  $(eval $(RESTORE_ARGS):;@:)
endif

restore:
	@test -n "$(RESTORE_ARGS)" || (echo "Usage: make restore -- <backup-file>" && exit 1)
	docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$${POSTGRES_USER:-decision_assistant}" -d "$${POSTGRES_DB:-decision_assistant}" \
		< "$(firstword $(filter-out --,$(RESTORE_ARGS)))"
