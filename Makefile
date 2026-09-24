.PHONY: build up down logs test-api test-web migrate smoke install start stop backup restore

build:
	docker compose build

up:
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

test-api:
	docker compose up -d db --wait
	API_BUILD_TARGET=test docker compose build api
	API_BUILD_TARGET=test docker compose run --rm api pytest

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
	docker compose exec -T db pg_dump -U "$${POSTGRES_USER:-decision_assistant}" "$${POSTGRES_DB:-decision_assistant}" \
		> "$(BACKUP_DIR)/backup-$$(date +%Y%m%d%H%M%S).sql"

# Usage: make restore -- <backup-file>
ifeq (restore,$(firstword $(MAKECMDGOALS)))
  RESTORE_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  $(eval $(RESTORE_ARGS):;@:)
endif

restore:
	@test -n "$(RESTORE_ARGS)" || (echo "Usage: make restore -- <backup-file>" && exit 1)
	docker compose exec -T db psql -U "$${POSTGRES_USER:-decision_assistant}" -d "$${POSTGRES_DB:-decision_assistant}" \
		< "$(firstword $(filter-out --,$(RESTORE_ARGS)))"
