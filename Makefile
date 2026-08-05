.PHONY: build up down logs test-api test-web migrate models smoke

build:
	docker compose build

up:
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

test-api:
	docker compose run --rm api pytest

test-web:
	docker compose run --rm web npm test -- --run

migrate:
	docker compose run --rm api alembic upgrade head

models:
	docker compose up -d ollama --wait
	docker compose exec ollama sh -lc 'ollama pull "$$OLLAMA_GENERATION_MODEL"'
	docker compose exec ollama sh -lc 'ollama pull "$$OLLAMA_EMBEDDING_MODEL"'

smoke:
	bash scripts/smoke.sh
