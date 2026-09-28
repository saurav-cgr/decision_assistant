---

description: "Task list for Single-Tenant Local Production Readiness"
---

# Tasks: Single-Tenant Local Production Readiness

**Input**: Design documents from `/specs/002-production-readiness/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api-additions.md, quickstart.md

**Tests**: included. AGENTS.md/Constitution IV require deterministic, layered coverage for new
behavior at its owning layer plus integration coverage for cross-layer flows; test tasks below
implement that requirement, not a separate TDD mandate from the spec.

**Organization**: grouped by user story (spec.md priorities) for independent implementation and
testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US8 per spec.md priorities (US1/US2/US3 = P1, US4/US5/US6 = P2, US7/US8 = P3)

## Path Conventions

Existing layout per plan.md: `api/src/decision_assistant/<module>/`, `api/tests/{unit,integration}/`,
`api/alembic/versions/`, `web/src/{pages,components}/`, `web/tests/`, repo-root `compose.yaml`,
`docs/`, `.github/workflows/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: production build tooling and localhost binding — no behavior change, unblocks every
story that needs a running, safely-bound stack to test against.

- [X] T001 Rewrite `api/Dockerfile` to a production install: drop `--editable '.[dev]'`, install
      only `dependencies` (not `[dev]` extras) via `pip install --no-cache-dir .`, keep the
      existing Docling model download, tesseract check, and `HF_HUB_OFFLINE=1`/
      `TRANSFORMERS_OFFLINE=1` env steps unchanged. Multi-stage: `base` (production, no dev
      deps) and `test` (`FROM base`, adds `[dev]`) — compose.yaml's `api` service build target
      selection happens in T003. (Reapplied 2026-09-24 after unexplained revert; see loop DB1.)
- [X] T002 [P] Rewrite `web/Dockerfile` as a multi-stage build: stage 1 `node:24-bookworm-slim` runs
      `npm ci && npm run build`; stage 2 serves `web/dist` as static files (nginx or a minimal
      static server), removing the `npm run dev` command and the `web_node_modules` bind-mount
      dependency for the runtime stage.
- [X] T003 Edit repo-root `compose.yaml`: remove the `api`/`web` `volumes: - .:/workspace` and
      `- ./web:/app` source bind-mounts (keep only `uploads_data`/named volumes); pin
      `ollama/ollama:latest` to a specific tag; remove the stale `PDF_PARSER: ${PDF_PARSER:-pypdf}`
      environment entry from the `api` service (per Constitution III, parser choice is
      code-enforced, not configurable).
- [X] T004 [P] Change every `ports:` mapping in repo-root `compose.yaml` from `"${X_PORT:-N}:N"` to
      `"127.0.0.1:${X_PORT:-N}:N"` for `api`, `web`, and `ollama`; remove the `db` service's
      `ports:` block entirely so Postgres is reachable only over the Compose network.
- [X] T005 [P] Add a root `Makefile` (or extend an existing one) with `install`, `start`, `stop`,
      `backup`, `restore` targets that wrap the corresponding `docker compose` commands, per
      quickstart.md Sections 1 and 5.
- [X] T006 [P] Update `.env.example` to remove `PDF_PARSER` and any credential-default entries that
      T003/US5 will replace with generated values; add a comment pointing to the first-run setup
      flow instead of a shared default.

**Checkpoint**: `docker compose config` shows no source bind-mounts and localhost-only port
bindings; `make install && make start` brings up a stack using only built images.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: shared schema and modules every user story's implementation tasks depend on.

**⚠️ CRITICAL**: no user-story task below may start until this phase is complete.

- [X] T007 Create Alembic revision `api/alembic/versions/0012_production_readiness.py` (new
      revision, `0001_initial.py` untouched per Constitution II) adding: `corpus_rebuilds` table
      per data-model.md (`id` UUID PK, `workspace_id` UUID FK → `workspaces.id`, `status` string
      constrained to `pending|running|completed|failed`, `reason` string, `documents_total` int,
      `documents_completed` int, `error` JSONB nullable, `started_at`/`finished_at` timestamptz
      nullable, `created_at`/`updated_at` timestamptz, plus a partial unique index on
      `(workspace_id) WHERE status IN ('pending','running')` enforcing one active rebuild per
      workspace); `decision_evidence.citation_stale` boolean `NOT NULL DEFAULT false`;
      `workspaces.disclosure_acknowledged_at` timestamptz nullable.
- [X] T008 [P] Add `CorpusRebuild` SQLAlchemy model in `api/src/decision_assistant/models.py`
      (or a new `api/src/decision_assistant/workspace/rebuild_models.py` if it would push
      `models.py` over 500 lines) matching T007's schema, using the existing `TimestampMixin`
      pattern.
- [X] T009 [P] Add `citation_stale` field to the `DecisionEvidence` model in
      `api/src/decision_assistant/models.py` and to `api/src/decision_assistant/decisions/schemas.py`
      response schema.
- [X] T010 [P] Add `disclosure_acknowledged_at` field to the `Workspace` model in
      `api/src/decision_assistant/models.py` and to `api/src/decision_assistant/workspace/schemas.py`.
- [X] T011 Create `api/src/decision_assistant/jobs/` package (new module, per plan.md structure)
      with `__init__.py`; move/generalize the existing dead-code sweep pattern from
      `api/src/decision_assistant/ingestion/jobs.py` into a shared `recover_and_requeue(session,
      *, max_attempts: int)` function usable by both ingestion and evaluation recovery (T019, T023).
- [X] T012 Add `max_ingestion_attempts` (default `3`) and `max_evaluation_attempts` (default `3`)
      fields to `Settings` in `api/src/decision_assistant/config.py`.
- [X] T013 Add startup config validation to `api/src/decision_assistant/config.py`: reject a
      missing or placeholder `AUTH_JWT_SECRET`/database password at `Settings` construction time
      with a specific, actionable error message (feeds US5 T029 and the `lifespan` failure path
      in T014). (Implemented as an explicit `validate_startup_config()` function, not a
      `Settings` model_validator — an unconditional validator would fire on every existing
      `Settings()` test construction across the suite before US5's secret-generation flow (T041)
      exists to supply real values. T045 (US5) is the task that wires this into a real blocking
      startup call site; see loop iterations.md Iteration 28.)
- [X] T014 Wire an automatic-migration step into `main.py`'s `lifespan` in
      `api/src/decision_assistant/main.py`: before serving requests, run `alembic upgrade head`
      programmatically (or shell out to the `alembic` CLI against `DATABASE_URL`), preceded by the
      pre-migration backup call from T024. (Iteration 28: auto-migration step wired via
      `api/src/decision_assistant/migrations.py` + `asyncio.to_thread` in `lifespan`. Iteration 29:
      checker V46 found two regressions in the auto-migration step — `alembic/env.py`'s
      `fileConfig` was silencing `uvicorn.error`/`uvicorn.access` for the life of the process, and
      `migrations.py`'s ini-path resolution broke under a non-editable install — both fixed and
      live-verified against a fresh DB with a non-editable production image. Iteration 37: the
      pre-migration backup precursor (T037, DB16/DB22) now runs first in `lifespan`, and must
      succeed before migration proceeds — see T037's note.)
- [X] T015 [P] Add `api/src/decision_assistant/diagnostics/__init__.py` package skeleton (new
      module per plan.md structure) — logging setup lands here in US7 (T033–T035).

**Checkpoint**: schema migrated, base modules importable, `alembic upgrade head` runs clean against
a fresh test database (`make test-api` still green).

---

## Phase 3: User Story 1 - Install and run without a dev environment (Priority: P1) 🎯 MVP

**Goal**: one install + one start command, on published images, no source mounts, localhost-only,
version visible in UI.

**Independent Test**: on a clean machine with only Docker Desktop installed, run `make install &&
make start` and reach the UI at a localhost URL with `docker compose config` showing no bind
mounts and no non-loopback port bindings.

### Implementation for User Story 1

- [X] T016 [US1] Add a `version` field to the `/health` response in
      `api/src/decision_assistant/main.py`, sourced from `Settings` or `pyproject.toml`
      `project.version`.
- [X] T017 [P] [US1] Add an "about"/version display to the web UI (`web/src/pages/` — reuse the
      existing settings or shell page) reading the `version` field from `/health`.
- [X] T018 [US1] Write `docs/install.md` documenting hardware requirements (Docling/OCR RAM needs,
      image size expectations per AGENTS.md) and the `make install && make start` flow, satisfying
      FR-027's install-doc portion.

**Checkpoint**: quickstart.md Section 1 passes — clean-machine install/start reaches the UI on
published images with localhost-only bindings and a visible version.

---

## Phase 4: User Story 2 - Ingestion survives interruption (Priority: P1)

**Goal**: an ingestion or evaluation job left `running` by a stop/crash/restart is detected on
startup and requeued (not left `processing` forever) up to a bounded attempt count.

**Independent Test**: start ingestion of a multi-page document, kill the API process mid-job,
restart, and confirm the document reaches `succeeded` or a clearly `failed` terminal state without
manual resubmission (quickstart.md Section 3).

### Tests for User Story 2

- [X] T019 [P] [US2] Unit test in `api/tests/unit/test_jobs_recovery.py` covering
      `recover_and_requeue` (T011): a `running` `IngestionJob` under `max_attempts` is requeued
      (status → `pending`, `attempt_count` incremented); a `running` job at/over `max_attempts` is
      marked `failed` with `error.code == "ingestion_interrupted"`.
- [X] T020 [P] [US2] Integration test in `api/tests/integration/test_ingestion_restart_recovery.py`
      simulating an API restart mid-ingestion (job left `running` in the DB) and asserting the
      startup sweep (T021) drives the document to a terminal state.

### Implementation for User Story 2

- [X] T021 [US2] Wire `recover_and_requeue` (T011) into `main.py`'s `lifespan` startup in
      `api/src/decision_assistant/main.py`, scanning `IngestionJob` rows with `status == "running"`
      and re-dispatching requeued jobs through the existing `DocumentService.dispatch` path (see
      `api/src/decision_assistant/documents/service.py`).
- [X] T022 [US2] Update `upload_documents` in `api/src/decision_assistant/documents/router.py:163`
      to record dispatch through the job table consistently with the recovery path (no behavior
      change to the request/response contract, only ensuring every `background_tasks.add_task`
      call has a corresponding `IngestionJob` row the sweep can find).
- [X] T023 [US2] Add the same recovery pattern for evaluation runs: extend `EvaluationRun` (add an
      `attempt_count` column via a follow-up migration step in T007 if not already present) and
      call `recover_and_requeue` for `EvaluationRun` rows with `status == "running"` from the same
      `lifespan` hook, covering `evaluation/router.py:142`. Done via Alembic revision
      `0013_eval_run_attempt_count`; swept `statuses=("running", "pending")` (DB27-class fix
      applied to evaluation from the start, not left as a known gap) via
      `error_field="failure"` (`EvaluationRun`'s failure column, not `error`).
- [X] T024 [US2] Surface the terminal `failed` state with a retry action in the document detail API
      response (`GET /documents/{document_id}` in `api/src/decision_assistant/documents/router.py`)
      so the UI (T025) can render it. Added `status`/`stage`/`progress`/`error` to `DocumentDetail`
      (same shape as `DocumentListItem`), populated from the document's latest `IngestionJob`.
- [X] T025 [P] [US2] Add a "failed — retry" state and retry button to the document list/detail view
      in `web/src/pages/` (documents page), calling the existing retry endpoint if present or the
      upload-resubmit flow otherwise. List view (`DocumentTable.tsx`) already had this; added it
      to the detail view (`SourceViewer.tsx`) using T024's new fields, reusing the shared
      `canRetryDocument`/`IngestionStatus` helpers extracted for both views. Checker V94 found
      this genuinely broken (stale open detail view + backend accepting a second concurrent
      retry) — fixed: `DocumentService.retry` now requires the document's LATEST job (not
      merely the latest `failed` one) to be `failed` before allowing a retry;
      `Workspace.tsx`'s `handleRetry` re-fetches the open detail after a successful retry.

**Checkpoint**: quickstart.md Section 3 passes for both ingestion and evaluation jobs.

---

## Phase 5: User Story 3 - Upgrade without losing decisions or history (Priority: P1)

**Goal**: `corpus_reset_required` triggers an automatic background rebuild from `uploads_data`,
migrations run automatically with a pre-migration backup, and decisions/conversations stay
readable throughout.

**Independent Test**: seed decisions/conversations/documents, force `corpus_reset_required` by
changing the chunking profile, restart, and confirm the rebuild completes automatically while
`GET /decisions` and conversation endpoints keep returning pre-upgrade data throughout
(quickstart.md Section 4).

### Tests for User Story 3

- [X] T026 [P] [US3] Unit test in `api/tests/unit/test_corpus_rebuild.py` asserting a rebuild only
      `DELETE`s the corpus-derived tables listed in data-model.md
      (`documents, document_versions, passages, embedding_cache, ingestion_jobs`; NOT a bare
      `TRUNCATE`, which ignores `ON DELETE SET NULL` — DB34/DB37) and never touches `decisions`,
      `decision_evidence`, `decision_relations`, `decision_revisions`, `conversations`,
      `conversation_messages`, `question_answers`, `evaluation_questions`, `evaluation_runs`,
      `evaluation_results`, or `retrieval_traces` (reclassified non-derived, DB37).
- [X] T027 [P] [US3] Integration test in `api/tests/integration/test_upgrade_rebuild_flow.py`:
      seed a workspace with a decision, a conversation, and an ingested document; flip the
      configured chunking/embedding profile; restart the app; assert
      `GET /workspace/{id}/corpus-rebuild` transitions `pending → running → completed` and
      `GET /decisions`/conversation endpoints return unchanged data at every polled point.
      (Iteration 64. Drives the real `lifespan` scan with a second app on a different chunking
      preset; the 404-before-first-row window is polled, and a gated embedding provider holds the
      rebuild open so `running` is observed with the reads verified stable. The poll compares
      `GET /api/v1/workspaces/{id}/decisions`, `.../conversations`, and
      `.../conversations/{id}` payloads exactly, normalizing only the `passage_id` /
      `document_version_id` / `stale` fields a completed rebuild legitimately rewrites. Also
      fixed quickstart.md Section 4's namespace and missing auth header, per the human report.)

### Implementation for User Story 3

- [X] T028 [US3] Implement `CorpusRebuildCoordinator` in
      `api/src/decision_assistant/workspace/rebuild/coordinator.py` (new file, per plan.md
      structure): on detecting `corpus_reset_required` (reusing
      `require_current_corpus_profiles`/`CorpusResetRequired` from
      `workspace/embedding_profile.py`), create a `CorpusRebuild` row (`status="pending"`,
      enforcing the T007 partial-unique-index single-active-rebuild constraint), then
      `DELETE` only the corpus-derived tables (T026's list; `truncate_corpus_derived_tables` in
      `workspace/rebuild/coordinator.py` already implements this half) inside a transaction, and
      re-dispatch ingestion for every document found in `uploads_data` using the existing
      ingestion pipeline (`ingestion/service.py`).
- [X] T029 [US3] Call `CorpusRebuildCoordinator` from `main.py`'s `lifespan` (after the T014
      auto-migration step) for every workspace currently flagged `corpus_reset_required`.
- [X] T030 [P] [US3] Add `GET /workspace/{workspace_id}/corpus-rebuild` and
      `POST /workspace/{workspace_id}/corpus-rebuild/retry` endpoints per
      contracts/api-additions.md to `api/src/decision_assistant/workspace/router.py`, returning
      404 when no rebuild has run and 409 on retry-while-active.
- [X] T031 [US3] After a rebuild completes, set `citation_stale = true` on `DecisionEvidence` rows
      whose `passage_id` no longer resolves (T009's field), never deleting the parent `decisions`
      row.
- [X] T032 [P] [US3] Add a rebuild-progress banner/indicator to the web UI
      (`web/src/components/`) polling `GET /workspace/{id}/corpus-rebuild` and showing
      `documents_completed`/`documents_total`, with a retry action on `failed`. (Iteration 69:
      `web/src/components/CorpusRebuildBanner.tsx` polls `getCorpusRebuild()`, shows `n/m documents`
      (or "starting…" before the total is known) with `role="status"`, reports a failed rebuild
      with the row's error code plus the reassurance that existing data is unchanged and a
      **Retry rebuild** button that calls `retryCorpusRebuild()` and resumes polling, and renders
      nothing when no rebuild has run (404 `corpus_rebuild_not_found`) — which is also what fixed
      DB45's false doc claim. Rendered from `web/src/pages/Workspace.tsx` above the document list.
      6 new tests in `web/src/components/CorpusRebuildBanner.test.tsx`; `make test-web` 51 passed.)
- [X] T033 [US3] Write `docs/upgrade.md` documenting the automatic migration + rebuild flow and
      when it triggers, satisfying FR-027's upgrade-doc portion. (Iteration 65: writes the new
      `docs/upgrade.md` — startup sequence, what triggers `corpus_reset_required` (preset,
      retrieval-unit strategy, embedding provider/model, parser profile), what a rebuild replaces
      vs preserves, evidence re-linking and `citation_stale`, progress/retry endpoints, DB43's
      all-or-nothing failure, and a backup warning against `docker compose down -v`. Also adds an
      "Upgrading to a new version" pointer from `docs/install.md`.)

**Checkpoint**: quickstart.md Section 4 passes; decisions/conversations survive a forced corpus
rebuild end-to-end.

---

## Phase 6: User Story 4 - Back up and restore user data (Priority: P2)

**Goal**: a user-triggered backup/restore command pair, plus a documented warning against
volume-deleting commands.

**Independent Test**: run backup, delete data volumes, restore, and confirm decisions,
conversations, and documents are back (quickstart.md Section 5).

### Tests for User Story 4

- [X] T034 [P] [US4] Integration test in `api/tests/integration/test_backup_restore.py` (or a
      shell-script test invoked from CI) that runs the backup script against a seeded test
      database/uploads volume, wipes the volumes, restores, and asserts row/file counts match.
      (Iteration 66: in-container real round trip — live `pg_dump` through
      `create_pre_migration_backup`, seeded workspace/document/version/passage/decision/evidence/
      conversation/message/trace, then the seeded rows and upload files are deleted and the
      archive is restored with `psql -v ON_ERROR_STOP=1`, the same invocation `scripts/restore.sh`
      uses. Row counts for every application table and the upload file list must match exactly.
      `scripts/restore.sh` itself cannot run inside the api container — it shells out to
      `docker compose exec` (DB22) — so the host-side script path stays quickstart Section 5's
      job / T070's CI job.)

### Implementation for User Story 4

- [X] T035 [US4] Add `scripts/backup.sh` producing
      `decision-assistant-backup-<UTC timestamp>.tar.gz` containing a `pg_dump` (via the `db`
      service's `pg_dump`) and a tar of the `uploads_data` volume contents, written to a
      user-chosen host directory outside Docker volumes.
- [X] T036 [P] [US4] Add `scripts/restore.sh <backup-file>` reversing T035: restores the `pg_dump`
      into the `db` service and extracts the uploads tar into the `uploads_data` volume.
- [X] T037 [US4] Reuse `scripts/backup.sh` from T035 as the pre-migration backup call referenced by
      T014 (single implementation, two call sites: startup auto-backup and user-triggered
      `make backup`). (Iteration 36: `make backup`/`make restore` delegate to
      `scripts/backup.sh`/`scripts/restore.sh`. Iteration 37, resolving DB22 per human decision:
      the startup auto-backup half needed a genuinely separate implementation, not literal reuse —
      `scripts/backup.sh` shells out to `docker compose exec`, which the in-container `lifespan`
      hook can't reach. Added `api/src/decision_assistant/backup.py`
      (`create_pre_migration_backup`), calling `pg_dump`/tar directly against `DATABASE_URL` and
      the mounted uploads volume, producing the SAME archive layout (`database.sql` +
      `uploads.tar`) so `scripts/restore.sh` reads either interchangeably — human-approved new
      `postgresql-client-16` dependency (exact-matched to the `pgvector/pgvector:pg16` server via
      the PGDG apt repo; Debian's own repo only offers mismatched major versions that produce
      dumps the pinned server's `psql` can't restore — reproduced and fixed live) plus a
      human-approved `./backups` host bind-mount into `api` at `/workspace/backups`, so both
      backup call sites write to the same host-visible directory.)
- [X] T038 [P] [US4] Write `docs/backup-restore.md` with the `make backup`/`make restore` commands
      and a prominent warning against `docker compose down -v`, satisfying FR-009 and FR-027's
      backup/restore-doc portion. (Iteration 79: writes `docs/backup-restore.md` — both commands
      and their script equivalents, archive layout, the FR-009 warning against `down -v` (plus
      `docker volume rm`/`system prune --volumes`), the automatic pre-migration backup and its
      retention, and the two known restore residuals from DB51/DB52 (restart `api` afterwards;
      upload extraction is additive; the scripts read `POSTGRES_USER`/`POSTGRES_DB` from the
      environment, not `.env`). Every command, path and setting checked against `Makefile`,
      `scripts/backup.sh`, `scripts/restore.sh`, `api/src/decision_assistant/backup.py`,
      `compose.yaml` and `config.py`; linked from `docs/install.md`.)

**Checkpoint**: quickstart.md Section 5 passes.

---

## Phase 7: User Story 5 - First-run setup with no shared secrets (Priority: P2)

**Goal**: `AUTH_JWT_SECRET` and DB password generated on first run; provider API key entered once,
never logged; startup fails fast on invalid config; local password replaces env bootstrap
credentials.

**Independent Test**: run first-run setup on a clean install and confirm generated, non-default
secrets in `.env`, and that the app refuses to start on a placeholder secret (quickstart.md
Section 2).

### Tests for User Story 5

- [X] T039 [P] [US5] Unit test in `api/tests/unit/test_config_validation.py` asserting `Settings`
      construction raises a specific, actionable error when `AUTH_JWT_SECRET` or the DB password
      is missing or equals a known placeholder value. (Iteration 91: **wording deviation recorded
      in the test file itself** — T039 asks for `Settings` *construction* to raise, and the project
      deliberately validates in `lifespan` instead (T013, DB17, M-018) so the existing suite can
      build a bare `Settings()` for behaviour unrelated to auth; the human confirmed that reading
      on 2026-09-26, so the behaviour these cases pin is `validate_startup_config`, which is what
      `lifespan` calls before any DB access. Three cases added on top of the DB17 set: `Settings`
      no longer has `auth_bootstrap_username`/`auth_bootstrap_password` at all (worth asserting
      because `extra="ignore"` would silently swallow a resurrected field, and with it a stale
      `.env` entry); a configuration shaped exactly like `make setup`'s output — real 64-char hex
      secret, non-placeholder `DATABASE_URL`, **no** bootstrap credentials — starts; and a real
      `AUTH_JWT_SECRET` is not enough while the database password is still the shared placeholder.)
- [X] T040 [P] [US5] Unit test in `api/tests/unit/test_first_run_setup.py` asserting the
      secret-generation step produces a unique `AUTH_JWT_SECRET` and DB password per run (no
      shared default) and that provider API keys are never present in generated log output.
      (Iteration 90: 14 test items. Uniqueness: 200 consecutive draws are distinct per field **and**
      the two fields of one draw differ, since one leak must not compromise both; values are
      full-length lowercase hex (the property the `ALTER ROLE` step relies on); `generate_secret`
      refuses a request under 16 bytes. Secrecy: the CLI's log file carries the key *names* and none
      of the generated secrets, the `DATABASE_URL` that embeds the password, or the configured
      Gemini key. Behaviour: blank values are filled while comments, ordering and unowned keys
      survive; real values are kept unless `overwrite=True`; a placeholder `POSTGRES_PASSWORD` is
      replaced while a hand-rotated `DATABASE_URL` is not — and that asymmetry is asserted in
      `applied`/`skipped`, which is what caught the implementation always reporting `skipped` empty.
      Mutation check: a deterministic generator fails exactly the two randomness-dependent tests
      (2 failed, 12 passed in the focused file).)

### Implementation for User Story 5

- [X] T041 [US5] Add `api/src/decision_assistant/setup/__init__.py` and
      `api/src/decision_assistant/setup/bootstrap.py` (new package per plan.md structure)
      implementing first-run secret generation (cryptographically random `AUTH_JWT_SECRET` and DB
      password) written to a local `.env` the app manages. (Iteration 90. **Deviation,
      human-approved and recorded as DB58:** the `.env` is written by a host command, not "by the
      app" — the container cannot write the file Compose substitutes from, and the only mount that
      would let it is the repo root, forbidden by D4. So `scripts/setup.sh` (host, `make setup`)
      owns the file and `decision_assistant.setup.bootstrap` owns every decision, the same
      host-script + in-container-module split already approved for T037/DB22: the module generates
      the secrets, derives the `DATABASE_URL` that carries the password, decides per key whether to
      fill or keep, and exposes an `env`/`status` CLI (current `.env` on stdin, updated `.env` on
      stdout). The script creates `.env` from `.env.example` at mode 600, asserts all three keys
      came back before atomically replacing the file, then starts `db` and rotates the role password
      with `psql` over stdin — never as an argv value (DB26) — after asserting the role name is a
      plain identifier and the password is the generator's 64-char hex form. Secrets are hex on
      purpose: the same string has to survive a `.env` line, a SQL literal and a URL password with
      no escaping. `config.PLACEHOLDER_DB_CREDENTIALS` is now the public single source of truth for
      the DB8/DB26 placeholder check instead of a second copy of the string. `docs/install.md`'s
      first-run section rewritten to lead with `make setup`.)
- [X] T042 [US5] Replace `AUTH_BOOTSTRAP_USERNAME`/`AUTH_BOOTSTRAP_PASSWORD` env-based bootstrap in
      `api/src/decision_assistant/auth/bootstrap.py` and `main.py`'s `_bootstrap_credentials` with
      a first-run "create password" flow backed by `GET /setup/status` and
      `POST /setup/password` per contracts/api-additions.md, keeping the existing password-reset
      path but making it local-only (no remote dependency). (Iteration 91: `auth/bootstrap.py`
      rewritten — `BootstrapService.ensure_user` became `SetupService.status()`/
      `create_password()`, plus `SETUP_USERNAME` and `PasswordAlreadySetUp` (409) — and `main.py`'s
      `_bootstrap_credentials` plus the startup user creation are gone, so a fresh install serves
      requests with **no user at all** and the first-run flow is the only way to create one.
      `auth_bootstrap_username`/`auth_bootstrap_password` were removed from `Settings`,
      `compose.yaml`, `.env.example` and the log-scrubbing secret set, and 19 now-dead bootstrap
      references were cleaned out of six test files (the two that asserted the bootstrap password
      was scrubbed/bundled now assert the same for the remaining secrets). **The password-reset path
      needed no change and got none:** it was already local-only (recovery code +
      `PasswordManager`), so this task's "making it local-only (no remote dependency)" clause was
      already satisfied — recorded rather than re-implemented. Adoption of unowned workspaces moved
      from startup into `create_password`, so setting a password cannot lock an operator out of data
      that already exists.)
- [X] T043 [P] [US5] Add `GET /setup/status` and `POST /setup/password` routes in
      `api/src/decision_assistant/auth/router.py`, reachable without a JWT while
      `needs_password_setup == true`. (Iteration 91: new `setup_router` at `/api/v1/setup`, mounted
      in `main.py`, with both routes deliberately carrying **no** JWT dependency — on a fresh install
      there is no user to authenticate, which is the point of the flow. `POST /password` returns the
      same `AuthResponse` as login, including the recovery code (the one moment it can be captured;
      without it a forgotten password is unrecoverable), and 409 `password_already_set_up` on the
      second call. Seven integration tests in `test_setup_flow.py` drive the real routes with the
      real service, password manager and token issuer; deleting the 409 check fails exactly the two
      tests that assert it. Recorded as DB59: `/auth/signup` is open too, so `needs_password_setup`
      is a first-run hint rather than an authorization boundary — pre-existing
      single-tenant/localhost behaviour, not introduced here.)
- [X] T044 [P] [US5] Add a first-run "create password" screen to the web UI
      (`web/src/pages/`), gating the rest of the app until `POST /setup/password` succeeds.
      (Iteration 92: `web/src/pages/FirstRunSetup.tsx` plus `web/src/app/SetupContext.tsx`, with
      `App.tsx`'s gate reworked. Two steps on purpose: the screen shows the recovery code and waits
      for "I saved my recovery code" before entering the app, mirroring `Authentication`'s sign-up
      flow, because `POST /setup/password` returns that code exactly once. `App.tsx` now waits for
      the status probe before choosing a screen — rendering the sign-in form first would ask a fresh
      install's operator to sign in to an account that cannot exist yet — and falls back to the
      sign-in form when the probe fails, so an install that already has a user is never locked out by
      this new gate. 5 new tests (`FirstRunSetup.test.tsx`) plus the two existing `App.test.tsx`
      cases adapted to answer the probe. **The new tests found a real bug in the gate**: clearing
      `needs_password_setup` immediately after the POST re-evaluated the gate and unmounted the
      recovery-code step, losing the code for good; fixed in `SetupContext` with the reason recorded
      at the call site. `make test-web` → 15 files, **64 passed** (which also runs `tsc -b`); the API
      gate was re-run as well because an API file changed in this increment.)
- [X] T045 [US5] Wire T013's config validation into `main.py` startup so the app fails fast with
      the specific error message when required config is missing/invalid, before attempting to
      serve traffic.

**Checkpoint**: quickstart.md Section 2 passes; no shared-default secret exists in a fresh install.

---

## Phase 8: User Story 6 - Privacy and offline mode (Priority: P2)

**Goal**: first-run disclosure of where document text goes, gating upload until acknowledged;
documented offline (Ollama) mode; provider switch confirmed as triggering a rebuild.

**Independent Test**: on first run with the default cloud provider, confirm the disclosure appears
before upload is possible; confirm switching providers after ingestion requires rebuild
confirmation (quickstart.md Section 2, extended).

### Tests for User Story 6

- [X] T046 [P] [US6] Integration test in `api/tests/integration/test_provider_disclosure.py`
      asserting `POST /documents/upload` returns 409 `disclosure_not_acknowledged` until
      `POST /workspace/{id}/provider-disclosure/ack` has been called. (Iteration 85: two tests. The
      gate test drives the real route with the real `DocumentService` and asserts 409
      `disclosure_not_acknowledged` **and no `Document` row created**, then 200 ack → 202 accepted
      with exactly one document. The second asserts a non-owner's upload is 404
      `workspace_not_found` and, notably, does **not** override `get_workspace_context`: the first
      attempt did override it, the upload then reached the disclosure check and answered 409 — a
      wrong assertion that hid the fact that ownership is the route dependency's job. Mutation check:
      removing the guard fails the gate test.)
- [X] T047 [P] [US6] Integration test in `api/tests/integration/test_provider_switch_confirmation.py`
      asserting a provider change that alters the embedding/chunking profile returns 409 without
      `confirm_rebuild: true` and creates a `CorpusRebuild` (US3, T028) when confirmed. (Iteration
      89: 7 tests. The refusal test asserts the 409 carries a *preview* (`documents_total` plus both
      profiles) **and** that nothing happened — no `app_settings` row, no `CorpusRebuild`, no
      dispatch. The confirmed path asserts 202, the persisted row, the in-process `settings`
      mutation, one `CorpusRebuild(reason="provider_switch")` and exactly one dispatched task. The
      other five cover a generation-only change (200, no rebuild), a switch to a provider whose
      credentials are missing (409, nothing persisted), an unknown provider name (422), a confirmed
      switch while a rebuild is active (409, no second row), and a non-owner (404). Mutation check:
      forcing `profile_changed = False` fails exactly the three gate-dependent tests and leaves the
      four unaffected ones green.)

### Implementation for User Story 6

- [X] T048 [US6] Add `GET /workspace/{workspace_id}/provider-disclosure` and
      `POST /workspace/{workspace_id}/provider-disclosure/ack` routes per
      contracts/api-additions.md to `api/src/decision_assistant/workspace/router.py`, persisting
      to `disclosure_acknowledged_at` (T010). (Iteration 81: both routes added, owner-scoped like
      every other workspace route, plus `ProviderDisclosureResponse` in `workspace/schemas.py`,
      `WorkspaceService.acknowledge_provider_disclosure` (idempotent — the first acknowledgement is
      kept, not re-stamped, so "when did the user accept this?" stays answerable), and a new
      `providers/disclosure.py` holding the two facts the disclosure states: `active_provider` (the
      generation provider) and `sends_document_text_remotely` (True unless *every* configured
      provider is in `OFFLINE_PROVIDERS`, so an unrecognised provider name fails toward disclosing
      more, not less). New `api/tests/integration/test_provider_disclosure.py`, 7 tests. The upload
      guard that consumes the acknowledgement is T049 and is still `[ ]`, so T046 stays open too.)
- [X] T049 [US6] Add the 409 `disclosure_not_acknowledged` guard to
      `upload_documents` in `api/src/decision_assistant/documents/router.py`. (Iteration 85:
      implemented in `documents/service.py`'s `submit_uploads` instead of the router — a deliberate
      deviation from this task's wording, because the rule then holds for every caller of the upload
      path rather than only for callers that remember to depend on a route-level guard; the route is
      still the only HTTP entry point. New `DisclosureNotAcknowledged` (409, non-retryable) checked
      right after the workspace is resolved, on the session the route already uses. Callers updated so
      nothing regresses: `tests/support/document_fixtures.py` and `test_backend_vertical_slice.py`
      create pre-acknowledged workspaces (their tests are about upload mechanics), and both HTTP
      scripts acknowledge first — `scripts/ingest_corpus.py` gained
      `_acknowledge_provider_disclosure` so the documented corpus-reset flow keeps working, and
      `scripts/smoke.py` acks once it has bound its workspace.)
- [X] T050 [US6] Add `POST /workspace/{workspace_id}/provider` per contracts/api-additions.md,
      returning 409 with rebuild-preview details when `confirm_rebuild` is absent/false and a
      profile-affecting change is requested; on confirmed switch, triggers the T028
      `CorpusRebuildCoordinator`. (Iteration 89. Persistence is a new single-row `app_settings` table
      (revision `0017_app_settings`) holding the generation and embedding provider names — the human
      approved this over the per-workspace shape this task's wording implies, because there is one
      process and therefore one effective provider; the global-store-vs-per-workspace-route
      asymmetry is recorded as DB57. `workspace/provider_config.py` owns the model and the four
      helpers; `main.py`'s `lifespan` applies the stored row over the environment defaults before
      anything resolves a provider or a corpus profile, so a restart converges on the selected
      configuration. The route is owner-scoped, keeps `tasks.md`'s no-side-effect refusal path, and
      on a confirmed profile change creates the `CorpusRebuild` row, swaps
      `app.state.provider_bundle_factory` for a fresh `CachedProviderBundleFactory(settings)` (the
      cached bundle was built from the old provider), dispatches `dispatch_pending_rebuild` as a
      background task and answers 202. Two error classes were added beyond the plan:
      `ProviderSwitchNotConfigured` (409) refuses a switch whose credentials are missing rather than
      persisting a configuration that would only fail later, after a partial rebuild (DB43 rolls the
      whole rebuild back), and `CorpusRebuildInProgress` (409) reuses the T030 invariant. See
      iterations.md Iteration 89 for evidence and risks.)
- [X] T051 [P] [US6] Add a first-run provider-disclosure screen to the web UI
      (`web/src/pages/`), naming the active provider and stating whether document text leaves the
      machine, gating the upload page until acknowledged.
      (Iteration 94: `web/src/pages/ProviderDisclosure.tsx` exports `ProviderDisclosureGate`, which
      reads `GET .../provider-disclosure` and renders the source library only once
      `acknowledged_at` is set — otherwise it names the active provider, states in plain words
      whether text leaves the machine, and offers the ack. Uploads are refused server-side with 409
      `disclosure_not_acknowledged` until then, so this is the UI half of an enforced rule, not the
      rule. It **fails closed**: an unreadable disclosure hides the library and offers a retry
      rather than offering an upload that will be refused. `Workspace.tsx` wraps its page in the
      gate; the rest of the shell keeps working. 5 tests in `ProviderDisclosure.test.tsx`, including
      the fail-closed case, plus the two Workspace suites adapted to the gate.)
- [X] T052 [P] [US6] Add a provider-switch confirmation dialog to the web UI settings page showing
      the pending-rebuild warning before resubmitting with `confirm_rebuild: true`.
      (Iteration 94: `web/src/components/ProviderSettings.tsx`, rendered from the Account (settings)
      page, with the provider calls in `web/src/api/provider.ts`. The 409
      `provider_switch_requires_rebuild` is treated as control flow, not an error: it opens an
      `alertdialog` built from the server's own payload (`documents_total`, current and proposed
      embedding profiles), and confirming resubmits the same body with `confirm_rebuild: true`.
      Cancel resubmits nothing. 4 tests, including that the second call is the *only* confirmed one.)
- [X] T053 [P] [US6] Write `docs/providers.md` documenting the Ollama fully-offline setup steps and
      a basic hardware-suitability check, satisfying FR-015 and FR-027's provider-doc portion.
      (Iteration 94: `docs/providers.md` — the two-provider model and what makes text leave the
      machine; the Ollama profile-gated setup (start the service, pull both models, point `.env` at
      `http://ollama:11434`, restart) and how to confirm nothing is sent out; a hardware-suitability
      check with a rule of thumb, a table, and commands that measure the real model on the real
      machine; the switch over UI and HTTP with its error codes; and the known limits (the active
      embedding provider is not reported before a switch, DB57's process-wide store, and a switch to
      an unreachable provider succeeding). Linked from `docs/install.md`.)

**Checkpoint**: disclosure blocks upload until acknowledged; provider switch requires explicit
rebuild confirmation.

---

## Phase 9: User Story 7 - Diagnosability without telemetry (Priority: P3)

**Goal**: structured, secret-scrubbed rotating file logs; a downloadable diagnostics bundle; no
telemetry sent anywhere by default.

**Independent Test**: trigger an error, download the diagnostics bundle, and confirm it contains
logs/version/config with zero secret values (quickstart.md Section 7).

### Tests for User Story 7

- [X] T054 [P] [US7] Unit test in `api/tests/unit/test_log_scrubbing.py` asserting the logging
      filter redacts `GEMINI_API_KEY`, `AUTH_JWT_SECRET`, and DB-password values from any log
      record they appear in. (Iteration 80: 9 tests — every configured secret value collected
      (gemini key, JWT secret, bootstrap password, DB password parsed out of `DATABASE_URL`),
      longest-first replacement order, an unparsable `DATABASE_URL` ignored rather than fatal,
      redaction of the message and of both tuple and dict `args` with the formatter out of the
      picture, redaction of a secret inside an exception traceback with the filter out of the
      picture, the "no minimum length" rule, and the end-to-end file: rotation plus a secret
      absent from every rotated file. Mutation-checked both ways — making `scrub_secrets` a
      no-op fails 5 of the 9, and deleting the `formatException` override fails only the
      traceback test, which is what makes the two scrubbing layers separately load-bearing.)
- [X] T055 [P] [US7] Unit test in `api/tests/unit/test_diagnostics_bundle.py` asserting the
      generated bundle's config dump uses an allowlist of safe fields (fails closed on unknown
      fields) and contains zero occurrences of any configured secret value. (Iteration 82: 7 tests —
      dump keys ⊆ allowlist with scalar-only values while still carrying the useful provider facts;
      no configured secret value (or the `DATABASE_URL` string, or its username) appears in **any**
      archive member; an adversarial case that allowlists `gemini_api_key`/`auth_jwt_secret`/
      `auth_bootstrap_password`/`database_url`/`ollama_base_url` on purpose and asserts they still
      ship nothing; the active log plus its rotated `.1` sibling are included while an unrelated file
      in the same directory is not; a bundle still builds with no log directory at all; the version
      and database revision are reported verbatim; and the archive is a readable zip. Mutation-checked
      with per-test attribution: disabling the credential-name guard fails **only** the adversarial
      test; returning no log files fails **only** the rotated-log test.)

### Implementation for User Story 7

- [X] T056 [US7] Implement rotating file logging in
      `api/src/decision_assistant/diagnostics/logging.py` (stdlib `logging` +
      `RotatingFileHandler`) with a scrubbing filter, wired into `main.py`'s app construction so
      all request/error logs go through it. (Iteration 80: new `diagnostics/logging.py` —
      `secret_values`, `scrub_secrets`, `SecretScrubbingFilter`, `SecretScrubbingFormatter`,
      `configure_logging`. Two scrubbing layers on purpose: the filter cleans the record's own
      fields so no other handler can leak them, and the formatter cleans the rendered message,
      exception traceback and stack, which the filter cannot reach because a traceback only
      becomes text during formatting. `configure_logging` attaches one marked `RotatingFileHandler`
      to the root *and* to `uvicorn`/`uvicorn.error`/`uvicorn.access` (uvicorn gives those their
      own handler and `propagate = False`, so root alone would miss every request line and
      traceback), and replaces only its own handlers on a second call, closing the superseded ones.
      New `Settings` fields `log_directory` (`/workspace/logs`), `log_level`, `log_max_bytes`,
      `log_backup_count`; called from `create_app` rather than `lifespan` so a startup failure is
      itself logged. `_startup_logger` still goes through `uvicorn.error` deliberately, because
      `docker compose logs` reads stdout/stderr.)
- [X] T057 [US7] Implement `api/src/decision_assistant/diagnostics/bundle.py` producing a zip of
      log files, `alembic current` output, app version, and an allowlisted sanitized `Settings`
      dump. (Iteration 82: new `diagnostics/bundle.py` — `BUNDLE_SETTINGS_FIELDS` (providers, models,
      profiles, limits; no secrets, no URLs, no filesystem paths), a second name-based credential
      guard (`_CREDENTIAL_NAME_PARTS`) because `database_url`/`ollama_base_url` are plain strings, and
      a scalar-only value filter so a `SecretStr` cannot serialize even if allowlisted. Split into a
      pure `assemble_bundle(settings, *, database_revision=...)` and an async `build_bundle(settings)`
      so the interesting half is testable without a database; `migrations.current_db_revision` is a
      new public wrapper around the read `is_upgrade_pending` already used, rather than shelling out
      to `alembic` inside a request path. The route (T058) and web action (T059) are still `[ ]`.)
- [X] T058 [P] [US7] Add `GET /diagnostics/bundle` per contracts/api-additions.md to a new
      `api/src/decision_assistant/diagnostics/router.py`, registered in `main.py`, requiring
      authentication. (Iteration 86: new router with `GET /api/v1/diagnostics/bundle`, mounted in
      `main.py`, authenticated via `Depends(get_current_user)` — host-level rather than
      workspace-scoped, as the contract says, but authenticated because the archive carries logs. The
      zip is assembled in memory (`build_bundle`) and returned with
      `Content-Disposition: attachment; filename="decision-assistant-diagnostics-<UTC>.zip"`, so no
      temporary file is written. Two new tests in `api/tests/integration/test_diagnostics_api.py`: no
      credentials → 401 with no zip body, and an authenticated download → 200
      `application/zip`, download headers, a readable zip with `version.txt` matching
      `get_app_version()`, a **non-empty** `alembic-current.txt` (the real database read, not a stub),
      and none of the configured secrets present anywhere in the response bytes. Mutation check:
      replacing the auth dependency makes **only** the 401 test fail.)
- [X] T059 [P] [US7] Add a "download diagnostics bundle" action to the web UI settings page
      (`web/src/pages/`). (Iteration 88: `client.ts` gained `downloadDiagnosticsBundle()` — an
      authenticated zip fetch, deliberately **not** `apiRequest`, which always parses JSON — plus
      `parseAttachmentFilename()` with a stable fallback name; new
      `web/src/components/DiagnosticsDownload.tsx` renders the action on the settings page
      (`Account.tsx`, T017's page) with a busy state, an `aria-live` status and a specific error
      alert, and `saveBundleBlob` hands the bytes to the browser as a download (object URL revoked on
      the next tick, not during the click). 6 new tests: 3 in `client.test.ts` (bearer token + server
      filename + body size; missing/malformed header fallback; API error mapping) and 3 in
      `DiagnosticsDownload.test.tsx` (save mechanics and deferred revoke; success status; disabled
      while preparing; error alert re-enabling the button). `make test-web` → 14 files, **59 passed**,
      exit 0, which also runs `tsc -b` in the build stage.)
- [X] T060 [US7] Confirm no metrics/error-reporting client is wired by default anywhere in
      `api/src/decision_assistant/` or `web/src/` (grep-verify, document as opt-in-only if a
      future opt-in is added — no code needed now since none currently exists). (Iteration 86:
      `grep -rniE "sentry|datadog|opentelemetry|prometheus|newrelic|posthog|statsig|segment\\.io|analytics|telemetry"`
      over `api/src`, `web/src`, `api/pyproject.toml` and `web/package.json` → **zero matches**, so no
      telemetry or error-reporting client is wired, directly or as a dependency. FR-019 therefore holds
      by construction today. No code written, as the task says; if a future opt-in is added it must be
      off by default and this grep, plus the D10 live check of the bundle, should be re-run.)

**Checkpoint**: quickstart.md Section 7 passes — bundle contains zero secret values.

---

## Phase 10: User Story 8 - Safe handling of untrusted uploads (Priority: P3)

**Goal**: magic-byte validation, size/page limits, and a parse timeout that can't wedge the
ingestion worker.

**Independent Test**: upload a mismatched-type file, an oversized file, and a slow/adversarial PDF;
confirm each is rejected/bounded and the worker recovers for the next upload (quickstart.md
Section 6).

### Tests for User Story 8

- [X] T061 [P] [US8] Unit test in `api/tests/unit/test_upload_validation.py` covering: content
      whose magic bytes don't match its declared type is rejected before parsing; a file over the
      configured page-count limit is rejected with a limit-naming error; the existing
      `MAX_UPLOAD_BYTES` size check still applies. (Iteration 83: 8 tests — a `.pdf` of prose, a
      `.docx` without a zip header, and binary content declared `.md` each raise
      `content_type_mismatch` with a sanitized message that names the extension but never the path;
      matching `.md`/`.pdf` content passes quietly; a 3-page PDF against `max_pdf_pages=2` raises
      `pdf_page_limit_exceeded` naming both the actual and configured counts; a `%PDF-` file pdfium
      cannot open is deliberately left to the parser; `_parse_for_ingestion` is driven with
      `parse_document` monkeypatched to fail if reached, proving validation runs first; and the
      byte-size cap still raises `StoredObjectTooLarge` with the partial file cleaned up.
      Mutation-checked with per-mutant attribution: disabling the magic-byte check fails 4 tests,
      disabling the page limit fails exactly 1.)
- [X] T062 [P] [US8] Integration test in `api/tests/integration/test_parse_timeout_recovery.py`
      using a Docling fixture designed to run long, asserting the parse times out, the document is
      marked `failed`, and a subsequent normal-document upload still succeeds (worker not wedged).
      (Iteration 87: one test that runs the **real** `LocalIngestionDispatcher` ->
      `IngestionService.ingest` path with deterministic fakes. The parse is made slow by patching
      `ingestion.service.parse_document` for `.pdf` only (5 s) rather than by shipping a huge fixture —
      what is under test is the timeout wiring, not Docling's speed — and the budget is patched where
      it is read (`ingestion_service.get_settings`, since `_parse_for_ingestion` uses the cached
      process-wide settings, not the dispatcher's object). Asserts the timed-out job is `failed` with
      `error == pdf_parse_timeout`, `retryable is False`, `finished_at` set and the version `failed`;
      then, on the same dispatcher and event loop, a normal `.md` document reaches `completed` with an
      `active` version. New shared helpers in `api/tests/support/ingestion_fixtures.py`
      (`FakeProviderBundleFactory`, `loop_local_dispatch_session_factory`, `cleanup_workspace`).
      Mutation check: `timeout=settings.model_timeout_seconds` → `timeout=3600` fails the test.
      Focused run 1 passed in 23.9 s.)

### Implementation for User Story 8

- [X] T063 [US8] Add a magic-byte content-type check in
      `api/src/decision_assistant/ingestion/` (new validation step ahead of `parse_document`),
      rejecting mismatches with a sanitized, non-retryable error code before Docling parsing
      begins. (Iteration 83: new `ingestion/validation.py` — `validate_document_content(path, *,
      max_pdf_pages)`. PDFs must start with `%PDF-`, `.docx` with the zip header, and `.md`/`.txt`
      must decode as UTF-8 with no NUL byte in the first 8 KB (text has no magic number). Rejections
      raise the existing `DocumentParseError` (422, non-retryable, sanitized) with code
      `content_type_mismatch`. Called from `ingestion/service.py`'s `_parse_for_ingestion`,
      immediately before `parse_document`, so `parse_document`'s frozen signature is untouched.
      Checker V136 then failed this task: the strict 8 KB probe decode rejected valid non-ASCII text
      whose multi-byte character straddled byte 8192 (DB55, medium). Fixed in iteration 84 — the probe
      is now read one byte past the window and decoded with an incremental UTF-8 decoder whose `final`
      flag tracks whether the file ended inside the window, with the checker's own probe as a
      regression test. Awaiting checker re-verification.)
- [X] T064 [US8] Add a configurable `max_pdf_pages` setting to `Settings`
      (`api/src/decision_assistant/config.py`) and enforce it in the same pre-parse validation
      step from T063, rejecting with an error naming the configured limit. (Iteration 83:
      `max_pdf_pages: int = Field(default=200, gt=0)` in `Settings`, enforced by the same
      `validate_document_content` call; the page count is read with `pypdfium2` (already a pinned
      dependency). Code `pdf_page_limit_exceeded`, message naming both the actual page count and the
      configured limit. A PDF whose page count cannot be read is not rejected here — Docling still
      fails it with its own sanitized error, so a library limitation cannot become a permanent
      "invalid file" verdict. Also added to the diagnostics bundle's allowlist.)
- [X] T065 [US8] Add/confirm a parse-level timeout around the Docling worker-thread call inside
      the existing ingestion task (per AGENTS.md: "Docling conversion runs in a worker thread
      inside the existing ingestion task"), mapping a timeout to the existing
      `pdf_parse_timeout` sanitized error code and ensuring the worker/task pool is released for
      the next job. (Iteration 87: **confirmed, not added.** `ingestion/service.py`'s
      `_parse_for_ingestion` already wraps the PDF branch in
      `asyncio.wait_for(asyncio.to_thread(parse_document, source_path),
      timeout=settings.model_timeout_seconds)` and maps `asyncio.TimeoutError` to
      `DocumentParseError("pdf_parse_timeout")`; the unit side was covered by
      `test_pdf_parser.py::test_docling_parse_timeout_is_sanitized`. What was missing was proof that
      the pool is released for the next job, which T062's integration test now supplies: the
      abandoned worker thread keeps sleeping while the next document ingests to `completed` on the
      same loop. No code changed.)

**Checkpoint**: quickstart.md Section 6 passes.

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: prompt-injection regression coverage, release process, remaining failure-state UX,
and CI — spans multiple stories.

- [X] T066 [P] Add adversarial prompt-injection fixtures to
      `api/tests/fixtures/` and a regression test in
      `api/tests/integration/test_prompt_injection_fixtures.py` asserting `AnswerVerifier` and
      abstention behavior match the equivalent clean-text fixture (FR-023). (Iteration 71:
      `injection-clean.md` + `injection-adversarial.md` share their real content and differ only
      by instruction-shaped lines; the test ingests both for real and asserts the verifier's
      *outcome* is identical for the same evidence-grounded answer, that the fixture's "skip the
      citation check" / "cite no sources" instructions are not obeyed (same abstention codes for
      both fixtures), that fixture text never enters `system_instruction`, and — recorded
      deliberately — that a quote from a passage the document really contains is still valid
      evidence, which is the verifier's contract rather than a hole.)
- [X] T067 [P] Add clear UI failure states for missing/invalid provider API key and provider-down
      to `web/src/pages/`/`web/src/components/` (FR-026, beyond the parse-retry and rebuild-
      progress states already covered in US2/US3).
      (Iteration 94: `web/src/components/providerFailure.ts` is one table of the ten provider/switch
      codes from `providers/base.py`, each mapped to a title and an *action* ("Set a valid
      GEMINI_API_KEY in .env and run `make start`", "confirm the service is running and
      OLLAMA_BASE_URL points at it") rather than restating the server string. It is used in three
      places, so the same failure reads the same way everywhere: the answering path
      (`Ask.tsx`'s error message), the ingestion path (`IngestionStatus.tsx`'s failed branch, where
      a provider failure previously showed the parser table's fallback or the raw message), and the
      provider switch (`ProviderSettings.tsx`). 4 tests in `IngestionStatus.test.tsx`, including
      that parser failures keep their own wording and an unrecognised code still falls back to the
      server's message. The `code` is read structurally rather than with `instanceof
      ApiClientError`, because a test that partially mocks the API client module would make an
      `instanceof` against an undefined binding throw instead of returning false.)
- [X] T068 Adopt semantic versioning for `api/pyproject.toml` `project.version` and `web/package.json`
      `version`; add a `CHANGELOG.md` entry format that states whether a release triggers a corpus
      rebuild on upgrade (FR-025).
      (Iteration 94: both versions were already `0.1.0`, so "adopt" is made concrete as a single
      source of truth that is *enforced* rather than asserted in prose: `CHANGELOG.md` documents
      SemVer, names `api/pyproject.toml`'s `project.version` as the version of record (it is what
      `/health` and the settings page report), gives the entry format, and requires a
      `Corpus rebuild on upgrade: yes|no — <why>` line per release — with the table of profile
      inputs (`ingestion/profiles.py`) that decides which it is, so the answer is derivable instead
      of remembered. New `api/tests/unit/test_release_version.py` (4 tests) asserts both versions
      are SemVer, that they are equal, that the changelog has an entry for the released version, and
      that every entry states its rebuild impact *and* the reason. `compose.test.yml` mounts
      `web/package.json` and `CHANGELOG.md` read-only, the same way `scripts/` and `evaluation/`
      are, since both live outside the `api` build context.)
- [X] T069 [P] Write `docs/uninstall.md` and `docs/troubleshooting.md`, completing the FR-027
      documentation set alongside T018/T033/T038/T053.
      (Iteration 94: `docs/uninstall.md` lists what lives where (containers, the four volumes by
      their real names, images, `.env`, `./backups`) and the order to remove it in, keeping
      "stop", "remove the software" and "delete the data" distinct — the last one behind the only
      irreversible flag. `docs/troubleshooting.md` is organised by symptom: startup
      `ConfigurationError`s (with the two real messages), an unhealthy `make start`, the Postgres
      password/`initdb` mismatch, rebuilds, the provider and upload error-code tables, the
      post-restore restart (DB51/DB52), the development-only evaluation 503, and disk/parse
      pressure (DB60/DB63). `docs/install.md` and the `README.md` troubleshooting table now link
      both, and the README's stale row telling operators to set `AUTH_BOOTSTRAP_USERNAME`/
      `AUTH_BOOTSTRAP_PASSWORD` — removed in iteration 91 — is corrected to `make setup`.)
- [X] T070 Add `.github/workflows/ci.yml`: backend lint, a typecheck, `make test-api`, `make test-web`,
      and a migration check (`alembic upgrade head` against a fresh Postgres service container in
      CI). **Amended at the human's direction (iteration 76):** "typecheck" is satisfied by the
      web's `tsc -b` production build in the `web-tests` job — which `make test-web` on its own does
      not run — and there is deliberately no API static type check, tracked as its own future
      increment in DB47 rather than silently omitted.
      (Iteration 73: four jobs — `lint` (ruff, pinned, installed by the job), `api-tests`
      (`make test-api`), `web-tests` (`make test-web` plus the `tsc -b` production build), and
      `migration-check` (a `pgvector/pgvector:pg16` service container + `alembic upgrade head`,
      `current` must report `(head)`, then a downgrade/re-upgrade to prove reversibility).
      **Two of the task's words are not fully covered and are escalated rather than faked** — see
      debt DB47: the API has no type checker (mypy reports ~100 errors on `src` with no config)
      and the web has no linter (no eslint configuration), so a blocking job for those would be a
      documented green check that checks nothing.)
      (Iteration 75, DB47 option (a): the lint half is now a declared, pinned `dev` dependency —
      `ruff==0.13.2` in `api/pyproject.toml` — so the `test` image installs it, a new `make lint-api`
      target runs it with the same `[tool.ruff]` config a developer gets, and the CI `lint` job reads
      the pin out of `pyproject.toml` instead of repeating it. `make lint-api` → `All checks passed!`
      on the rebuilt image. The typecheck gap (no API type checker, no web linter) is now DB47's
      remaining options (b)/(c)/(d), which is why D13 is still `pending`.)
- [X] T071 [P] Add `.github/workflows/release.yml`: on release tags, build and push pinned images
      and run a gitleaks secret scan; explicitly no benchmark-gate step (dropped per product
      direction).
      (Iteration 94: three jobs. `verify-version` fails the release before anything is published if
      the tag does not equal both declared versions or if `CHANGELOG.md` has no entry for it without
      the FR-025 `Corpus rebuild on upgrade:` line — the check is repeated here because a tag can be
      pushed onto a commit whose tests never ran in this workflow. `secret-scan` runs gitleaks with
      full history. `publish-images` (needs both) builds with `target: base`/`runtime` — never the
      `test` stage — and pushes each image under the release version **and** an immutable `sha-`
      tag, with SBOM and provenance; `latest` is deliberately not pushed, because a floating tag is
      what pinning is meant to avoid. The step summary records that no benchmark gate ran and points
      at the changelog for the upgrade impact. **Not yet run on a runner** — `.github/` is untracked
      and has never executed, same as `ci.yml`.)
- [X] T072 Run quickstart.md end-to-end (all 8 sections) against a clean checkout as the final
      acceptance pass.
      (Iteration 96: executed live against an isolated clean checkout — the working tree rsync'd to
      `/tmp/decision-assistant-qs` (no `.git`, no `.env`), with `COMPOSE_PROJECT_NAME=decision-assistant-qs`
      so no command touched the real `decision-assistant` project (verified: real image IDs unchanged).
      §1 install/start (images built, `/health` version, db port unpublished, no source bind-mounts,
      web shell 200); §2 `make setup` generated secrets (0 blank/example/bootstrap), password flow
      (`needs_password_setup` true→false, 409 on second POST), `ConfigurationError` on blank
      `AUTH_JWT_SECRET`; §3 SIGKILL mid-ingestion recovered — log `startup recovery: requeued 1
      ingestion job(s) (1 dispatched), marked 0 failed`, document `completed`, `attempt_count=1`,
      evaluation half 503 `evaluation_unavailable`; §4 profile change → `startup: 1 workspace(s) need a
      corpus rebuild` → `running 6/7` visible mid-run → `completed 7/7`, 17 decisions + 1 conversation
      unchanged, pre-migration backup present; §5 backup → down (no `-v`) → up → delete 1 decision →
      restore → 17 decisions + 7 documents back; §6 `content_type_mismatch`, `file_too_large`,
      `pdf_parse_timeout` (1 s budget), `.md` upload `completed`, api idle (0.26% CPU, 191 MiB); §7
      bundle 200/401/401 with `settings.json` + `alembic-current.txt` + `version.txt` + `logs/`, zero
      secret values (raw or percent-encoded) in the bundle; §8 CI is a process check — the workflow
      files map to real jobs but have never run on a runner (D13 checker-pass by inspection). Maker
      evidence, not a checker verdict.)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Phase 1 (needs the production Dockerfiles/compose to run
  migrations/tests against) — BLOCKS all user stories.
- **User Stories (Phases 3–10)**: all depend on Phase 2 completion.
  - US1, US2, US3 are P1 and have no inter-story dependency — can proceed in parallel.
  - US6 (Phase 8) depends on US3's `CorpusRebuildCoordinator` (T028) for its provider-switch
    rebuild trigger (T050) — implement after Phase 5, or stub T028 first if run in parallel.
  - US4 (Phase 6) reuses the backup mechanism from US3's auto-migration hook (T037 depends on
    T035) — implement T035 before T037, or before Phase 5's T014 is finalized.
  - US5, US7, US8 have no dependency on other stories.
- **Polish (Phase 11)**: depends on all desired stories being complete.

### Parallel Opportunities

- All `[P]`-marked Setup tasks (T002, T004, T005, T006).
- All `[P]`-marked Foundational tasks (T008–T010, T015) once T007's migration lands.
- US1, US2, US5, US7, US8 can be staffed in parallel once Phase 2 is done; US3 should land before
  US6; US3 should land before or alongside US4 (shared backup call).
- Within each story, test tasks marked `[P]` run in parallel with each other before
  implementation tasks begin.

---

## Parallel Example: User Story 2

```bash
Task: "Unit test in api/tests/unit/test_jobs_recovery.py"
Task: "Integration test in api/tests/integration/test_ingestion_restart_recovery.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: User Story 1
4. **STOP and VALIDATE**: quickstart.md Section 1
5. Demo: clean-machine install/start on published images, localhost-only, versioned.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → validate → MVP demo.
3. US2, US3 (both P1) → validate each independently → the three P1 stories together close the
   "biggest gap" identified in the product brief (durable ingestion + safe upgrades).
4. US4, US5, US6 (P2) → validate each → closes the remaining blockers.
5. US7, US8 (P3) → validate each.
6. Phase 11 polish → final quickstart.md full pass.
