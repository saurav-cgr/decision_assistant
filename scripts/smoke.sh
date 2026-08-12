#!/usr/bin/env bash

set -euo pipefail

cd "${0%/*}/.."

mode="${SMOKE_PROVIDER_MODE:-fake}"
smoke_project="decision-assistant-smoke-$$-$RANDOM"
case "$mode" in
  fake)
    compose_args=(
      -p "$smoke_project"
      -f compose.yaml
      -f compose.isolated.yaml
      -f compose.smoke.yaml
    )
    ;;
  gemini)
    compose_args=(
      -p "$smoke_project"
      -f compose.yaml
      -f compose.isolated.yaml
    )
    ;;
  *)
    echo "SMOKE FAIL: SMOKE_PROVIDER_MODE must be fake or gemini" >&2
    exit 2
    ;;
esac

cleanup() {
  smoke_status=$?
  trap - EXIT
  if ! docker compose "${compose_args[@]}" down \
    --volumes --remove-orphans --rmi local
  then
    if [[ "$smoke_status" -eq 0 ]]; then
      smoke_status=1
    fi
  fi
  exit "$smoke_status"
}
trap cleanup EXIT

if [[ "$mode" == "gemini" ]] && ! docker compose "${compose_args[@]}" \
  run --rm --no-deps api python -c \
  'import os, sys; sys.exit(0 if os.environ.get("GEMINI_API_KEY", "").strip() else 2)'
then
  echo "SMOKE FAIL: GEMINI_API_KEY is required for Gemini mode" >&2
  exit 2
fi

docker compose "${compose_args[@]}" up -d db --wait
docker compose "${compose_args[@]}" run --rm api alembic upgrade head
docker compose "${compose_args[@]}" up -d api web --wait

if [[ "$mode" == "gemini" ]]; then
  docker compose "${compose_args[@]}" run --rm api python -c \
    "import urllib.request; urllib.request.urlopen('http://api:8000/ready', timeout=10)"
fi

docker compose "${compose_args[@]}" run --rm api python ../scripts/smoke.py
