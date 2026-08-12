.PHONY: build up down logs test-api test-web migrate smoke

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
	docker compose run --rm api pytest

test-web:
	docker compose run --rm web npm test -- --run

migrate:
	docker compose run --rm api alembic upgrade head

smoke:
	bash scripts/smoke.sh
