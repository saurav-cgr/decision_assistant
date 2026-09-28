# Implementation Plan: Single-Tenant Local Production Readiness

**Branch**: `002-production-readiness` | **Date**: 2026-09-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-production-readiness/spec.md`

## Summary

Turn the current dev-mode stack (Vite dev server, editable API install, source bind-mounts, all
ports open on every interface, no durable job recovery, hard corpus-reset-on-profile-change) into
something a single user can install once via Docker Compose, run on their own machine, and upgrade
without losing decisions, conversations, or documents. Primary technical approach: production
container images (multi-stage web build served statically, non-editable API install), localhost-
only port binding, a Postgres-backed job-recovery sweep on API startup, an automatic background
corpus-rebuild path that reuses preserved `uploads_data` when `corpus_reset_required` fires,
generated-on-first-run secrets, structured file logging with secret scrubbing, and upload
validation (magic bytes, size/page limits, parse timeout). No new infrastructure (no Redis, no
message broker) — Postgres is the only durable store beyond the existing volumes.

## Technical Context

**Language/Version**: Python 3.12 (API), TypeScript 5.9 / React 19 (web), Node 24 (web build only)

**Primary Dependencies**: FastAPI 0.116, SQLAlchemy 2.0 (asyncio) + asyncpg, Alembic 1.16, Docling
2.130 (PDF parsing), google-genai (Gemini provider), Vite 7 / React 19 (web), Docker Compose

**Storage**: PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`), Docker-managed volumes
(`postgres_data`, `uploads_data`, `ollama_data`); no new datastore — job-recovery state lives in
Postgres, not Redis

**Testing**: pytest + pytest-asyncio (`make test-api`), Vitest + Testing Library (`make test-web`),
`docker compose run --rm api alembic upgrade head` as a migration-check gate

**Target Platform**: Linux/macOS/Windows host running Docker Desktop (or Docker Engine +
Compose plugin on Linux); no bundled desktop wrapper in scope (per spec Q1 resolution)

**Project Type**: web application (FastAPI backend + React frontend), distributed as Docker
Compose services — not a library, CLI, or mobile app

**Performance Goals**: not throughput-driven (single local user); startup job-recovery sweep and
corpus rebuild must not block API readiness for more than a few seconds before serving read
requests

**Constraints**: no source bind-mounts in the shipped `compose.yaml`; all published ports bound to
`127.0.0.1`; no outbound network calls at runtime beyond the configured model provider; secrets
never logged; corpus rebuild must not delete `Decision`/`Conversation`-owning tables; single
rebuild job at a time (per spec edge case)

**Scale/Scope**: one workspace, one local user, corpus sized to what a person ingests personally
(the existing Atlas benchmark corpus is the reference scale, not a target ceiling)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Secrets Never Leave the Machine** — PASS. Generated secrets (FR-010), diagnostics scrubbing
  (FR-018), and log scrubbing (FR-017) implement this principle rather than conflict with it.
- **II. Corpus Contract: Reset, Never Migrate** — PASS with clarified scope. The feature does not
  weaken the reset contract: `corpus_reset_required` still fires on profile change and reset still
  drops only Postgres and preserves `uploads_data`. What's new is *automating* the existing
  reset→reingest sequence and keeping non-corpus tables (decisions, conversations) outside that
  reset boundary — this requires confirming (Phase 0 research) which tables are corpus-owned vs.
  workspace-owned today, since automatic reset must not touch the latter.
- **III. Docling-Only, Local-Only PDF Parsing** — PASS. Upload safety (FR-020–FR-022) adds
  pre-parse validation; it does not touch parser selection. Removing stale `PDF_PARSER: pypdf`
  compose setting (spec item 6) aligns compose with this already-enforced principle.
- **IV. Deterministic, Layered Testing** — PASS. New behavior (job recovery, corpus rebuild
  orchestration, upload validation, secret generation) gets focused unit coverage at its owning
  layer plus integration coverage for the restart/rebuild flows, consistent with existing test
  layout (`api/tests/unit`, `api/tests/integration`).
- **V. Small Files, Clear Layers** — PASS, enforced during implementation. New orchestration
  (job-recovery sweep, rebuild coordinator) is backend Python; web only renders rebuild/job status
  the API reports. Files stay under 500 lines by splitting sweep/rebuild/backup concerns.

No violations requiring Complexity Tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/002-production-readiness/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/             # Phase 1 output
└── tasks.md               # Phase 2 output ($speckit-tasks — not created here)
```

### Source Code (repository root)

```text
api/
├── Dockerfile                        # change: production (non-editable) install, drop dev extras
├── compose.yaml (repo root)          # change: localhost binding, no source mounts, pinned tags
├── alembic/versions/                 # new revision(s) for job-tracking table, if needed
├── src/decision_assistant/
│   ├── main.py                       # change: startup sweep + auto-migrate hook call
│   ├── config.py                     # change: config validation, secret-generation wiring
│   ├── jobs/                         # new: durable job records + startup recovery sweep
│   ├── ingestion/                    # change: upload magic-byte/size/page checks, timeout
│   ├── workspace/
│   │   ├── embedding_profile.py      # existing corpus_reset_required detection (reused)
│   │   └── rebuild/                  # new: automatic background rebuild coordinator
│   ├── documents/router.py           # change: dispatch through job table, not bare BackgroundTasks
│   ├── evaluation/router.py          # change: same job-table dispatch
│   ├── diagnostics/                  # new: log scrubbing + diagnostics bundle export
│   └── setup/                        # new: first-run secret generation, password bootstrap
├── scripts/                          # new: backup.sh / restore.sh (or Make targets)
└── tests/
    ├── unit/                         # job recovery, upload validation, secret generation, scrub
    └── integration/                  # restart-mid-ingestion, corpus rebuild, backup/restore

web/
├── Dockerfile                        # change: multi-stage build → static assets served by nginx/API
├── src/pages/                        # change: first-run setup, provider disclosure, rebuild progress
├── src/components/                   # change: job/rebuild status indicators, failure-state banners
└── tests/                            # rebuild-progress, disclosure, first-run password UI tests

docs/                                  # new/changed: install, upgrade, backup/restore, providers,
                                        # uninstall, troubleshooting (FR-027)
.github/workflows/                     # new: CI (FR-028) — lint, typecheck, tests, migration check,
                                        # image build, secret scan on release tags
```

**Structure Decision**: existing FastAPI-monolith-plus-React layout is kept unchanged at the top
level (`api/`, `web/`). This feature adds narrowly-scoped modules (`jobs/`, `workspace/rebuild/`,
`diagnostics/`, `setup/`) inside `api/src/decision_assistant/` rather than new top-level services,
per Constitution V (small files, clear layers, no new infrastructure). No new runtime process is
introduced — the job-recovery sweep and rebuild coordinator run inside the existing API process at
startup and via the existing background-task mechanism, backed by Postgres.

## Complexity Tracking

> No Constitution Check violations. Table intentionally omitted.
