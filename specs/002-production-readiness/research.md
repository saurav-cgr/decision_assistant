# Phase 0 Research: Single-Tenant Local Production Readiness

## R1. Distribution mechanism

- **Decision**: Docker Compose with published, version-pinned images. End users install Docker
  Desktop (or Docker Engine + Compose plugin) as a prerequisite. No bundled desktop wrapper.
- **Rationale**: resolved directly by the user during `/speckit-specify` (spec Q1/A). Smallest
  delta from the current architecture — same services, same volumes, same Alembic/Docling
  toolchain — versus a from-scratch Tauri/Electron rebuild with an embedded Postgres and
  per-OS native packaging.
- **Alternatives considered**: bundled desktop wrapper (rejected — large new build surface,
  duplicate packaging of Docling/OCR models); "ship both" (rejected — doubles distribution
  surface before the Compose path is even proven).

## R2. Single-user auth necessity

- **Decision**: keep auth. Replace env-var bootstrap credentials (`AUTH_BOOTSTRAP_USERNAME` /
  `AUTH_BOOTSTRAP_PASSWORD`) with a first-run "create password" screen, plus a local password
  reset path. Keep the existing 24 h JWT TTL.
- **Rationale**: resolved by the user (spec Q2/A). Localhost-only binding (R3) stops the network,
  not other local users or processes on a shared machine.
- **Alternatives considered**: no auth at all (rejected — any local process/user gets full data
  access with zero friction).

## R3. Localhost-only binding

- **Decision**: change every `ports:` mapping in `compose.yaml` from `"${X_PORT:-N}:N"` to
  `"127.0.0.1:${X_PORT:-N}:N"`, and drop the `db` service's port publication entirely (the API
  reaches Postgres over the Compose network; only `db` needs no host mapping).
- **Rationale**: current `compose.yaml` publishes 5432 (Postgres, default credentials), 8000
  (API), 5173 (web dev server), and 11434 (Ollama) on `0.0.0.0` — reachable from any device on the
  same network. This is a one-line-per-port change with no architecture impact.
- **Alternatives considered**: firewall-level mitigation (rejected — relies on host configuration
  outside the app's control; the compose file should be safe by default).

## R4. Job durability across restarts

- **Existing infrastructure found**: `ingestion_jobs` table (`IngestionJob` model,
  `api/src/decision_assistant/models.py:446`) already tracks `pending | running | completed |
  failed` status per document with `stage`, `progress`, `attempt_count`, and `error`.
  `api/src/decision_assistant/ingestion/jobs.py` already defines `recover_stale_jobs()`, which
  marks `running` jobs `failed`/`interrupted` on a stale scan — but **this function is never
  called anywhere in the codebase**. It is dead code.
- **Gap**: (a) `recover_stale_jobs` is not wired into `main.py`'s `lifespan` startup, so stale
  "running" jobs currently stay stuck forever after a crash/restart, contradicting the "processing
  forever" symptom in the spec; (b) it only marks jobs failed, it does not requeue/resume them —
  spec FR-003 asks for recovery, not just a faster failure; (c) no equivalent exists for
  evaluation runs (`evaluation/router.py` `start_run` also uses bare `BackgroundTasks`).
- **Decision**: wire `recover_stale_jobs`-equivalent sweep into API startup (`lifespan`), extend
  it to *requeue* (re-dispatch) interrupted jobs rather than only marking them failed, cap
  requeue attempts using the existing `attempt_count` column, and add a parallel `EvaluationRun`
  status sweep using the same pattern. No new datastore — the existing Postgres tables are
  sufficient (per AGENTS.md: "you don't need Redis").
- **Alternatives considered**: a task queue (Celery/RQ + Redis) — rejected as disproportionate
  infrastructure for a single-user local app and explicitly out of scope per the product
  direction ("no new infrastructure").

## R5. Upgrade / corpus-rebuild without data loss

- **Existing infrastructure found**: `corpus_reset_required` is already detected per-workspace by
  `require_current_corpus_profiles()` (`workspace/embedding_profile.py`), comparing the
  configured embedding/chunking profile fingerprint against `Workspace.embedding_profile`. It
  currently only *raises* (`CorpusResetRequired`, mapped to an API error) — there is no automated
  reingestion path; the documented recovery is the manual `dropdb && createdb && alembic upgrade
  head && ingest_corpus.py` sequence in AGENTS.md.
- **Critical finding**: the documented manual reset (`dropdb`/`createdb`) drops the *entire*
  database, not just corpus tables. Table inventory (`models.py`, `evaluation/models.py`,
  `answering/history_models.py`, `answering/conversation_models.py`):
  - **Corpus-derived (safe to rebuild from `uploads_data`)**: `documents`, `document_versions`,
    `passages`, `embedding_cache`, `ingestion_jobs`, `retrieval_traces`.
  - **Non-derived, must survive a rebuild**: `users`, `workspaces`, `decisions`,
    `decision_evidence`, `decision_relations`, `decision_revisions`, `conversations`,
    `conversation_messages`, `question_answers`, `evaluation_questions`, `evaluation_runs`,
    `evaluation_results`.
  - A full `dropdb`/`createdb` — the only reset mechanism that exists today — destroys both
    groups. It cannot be reused as-is for an automatic, in-place upgrade rebuild.
- **Decision**: replace the destructive whole-database reset, for the *automatic* upgrade path
  only, with a scoped rebuild: `TRUNCATE` (or delete-and-reingest) only the corpus-derived tables
  listed above, inside a transaction, while leaving every non-derived table untouched. The manual
  `dropdb`/`createdb` sequence in AGENTS.md remains available as an explicit, human-invoked
  fallback for development/full resets, but the automated FR-006 rebuild path does not call it.
  `decision_evidence` rows reference `passages`; on rebuild, evidence citations that pointed at
  removed passages are treated as decisions whose *citation* is stale (flagged, not deleted) —
  the decision text and history are never deleted. This detail is a data-model concern, expanded
  in `data-model.md`.
- **Sequencing decision**: on startup, `alembic upgrade head` runs automatically (FR-005), guarded
  by a database backup taken immediately before (reusing the R6 backup mechanism). After
  migrations apply, the app checks `corpus_reset_required` per workspace; if set, it starts a
  background `CorpusRebuild` job (new entity, see data-model) that reingests from `uploads_data`
  using the existing ingestion pipeline, and the UI polls/shows its progress. Only one rebuild
  runs at a time (spec edge case) — enforced by a single active-rebuild row per workspace.
- **Alternatives considered**: keep the manual dropdb/createdb flow and just automate running it
  (rejected — destroys decisions/conversations, violates FR-007 directly); dual-write/shadow
  corpus with atomic swap (rejected as over-engineering for a single-user local scale — truncate
  and resequential-reingest is simple, auditable, and matches existing ingestion code paths).

## R6. Backup and restore

- **Decision**: two related mechanisms sharing one implementation:
  1. An internal pre-migration backup (FR-005), invoked automatically before `alembic upgrade
     head` on every startup, retained locally (rotated, e.g., keep last N).
  2. A user-triggered `backup`/`restore` command (FR-008), documented and runnable via `make` or a
     script, producing a timestamped archive containing a `pg_dump` of the database plus a tar of
     the `uploads_data` volume contents, stored outside the Docker volumes (host filesystem path
     the user chooses).
- **Rationale**: `pg_dump`/`pg_restore` against the existing `pgvector/pgvector:pg16` image needs
  no new tooling; `uploads_data` is already a named volume that can be tarred via a throwaway
  container mount. This matches "the user's data lives in two Docker volumes" from the product
  brief.
- **Alternatives considered**: continuous WAL archiving / PITR (rejected — disproportionate for a
  single local user; on-demand dump/restore is sufficient and far simpler to reason about).

## R7. Secrets and first-run config

- **Decision**: on first run (no `AUTH_JWT_SECRET` / DB password present and not a known
  placeholder), a setup step generates cryptographically random values and persists them to a
  local `.env` the user does not have to hand-edit. Startup validates required config and fails
  fast with a specific message (missing key, placeholder value, malformed value) rather than
  starting in a broken state. `PDF_PARSER: pypdf` and other stale compose settings are removed
  (parser choice is enforced in code per Constitution III already).
- **Rationale**: matches FR-010–FR-012; low-risk, additive change to existing `config.py`
  (`Settings`) validation.
- **Alternatives considered**: a settings UI for the DB password (rejected — DB password is
  internal wiring between `api` and `db` containers, never user-facing; only the model-provider
  API key needs a user-facing entry point).

## R8. Privacy / offline disclosure

- **Decision**: a first-run disclosure screen (web) naming the active provider and stating
  whether document text leaves the machine; acknowledgment is stored (a boolean/timestamp on the
  workspace or a local settings row) and gates the upload flow until accepted. Provider switch
  after ingestion routes through the same confirmation-then-rebuild flow as R5.
- **Rationale**: matches FR-014–FR-016; reuses existing provider configuration
  (`GENERATION_PROVIDER`/`EMBEDDING_PROVIDER`) already present in `compose.yaml` and `config.py`.

## R9. Logging and diagnostics

- **Existing state**: `api/src` has no structured logging today (confirmed — no `logging`
  configuration found in `main.py` or elsewhere beyond default Uvicorn access logs).
- **Decision**: add Python `logging` with a rotating file handler (stdlib
  `RotatingFileHandler`), a scrubbing filter/formatter that redacts known secret field names
  (`GEMINI_API_KEY`, `AUTH_JWT_SECRET`, DB password) before a record is emitted, and a
  diagnostics-bundle export (new `diagnostics/` module) that zips the log files plus a
  sanitized config/version dump. No telemetry is sent anywhere by default (FR-019).
- **Alternatives considered**: structured JSON logs to stdout only (rejected — Docker log
  retention is not guaranteed across `docker compose down`/restarts on a laptop; a file survives
  restarts the way stdout capture does not).

## R10. Upload safety

- **Existing state**: `MAX_UPLOAD_BYTES` already exists in `config.py`/`compose.yaml`; a model
  timeout (`MODEL_TIMEOUT_SECONDS`) already exists for provider calls, but no magic-byte check or
  page-count limit exists before Docling parsing begins.
- **Decision**: add a pre-parse validation step in the ingestion pipeline (magic-byte sniff
  against declared content type, page-count cap for PDFs, existing size cap enforced earlier in
  the request path) and a parse-level timeout wrapping the Docling worker-thread call (per
  AGENTS.md: "Docling conversion runs in a worker thread inside the existing ingestion task"),
  mapped to the existing sanitized non-retryable error codes.
- **Alternatives considered**: sandboxed/subprocess parsing per file (rejected — AGENTS.md already
  specifies worker-thread execution inside the existing ingestion task; changing that execution
  model is out of scope for this feature).

## R11. Prompt-injection regression fixtures

- **Decision**: add adversarial text fixtures (documents containing instruction-like text aimed
  at the model) to the existing fixture set, asserting the `AnswerVerifier` and abstention logic
  produce the same outcome as an equivalent clean fixture. Reuses existing deterministic,
  offline test patterns (Constitution IV) — no live-provider calls needed since verification is
  deterministic post-generation logic.

## R12. CI

- **Decision**: add GitHub Actions workflows: (1) a PR workflow running lint, typecheck,
  `make test-api`, `make test-web`, and a migration check (`alembic upgrade head` against a fresh
  Postgres service container); (2) a release-tag workflow building and pushing pinned images plus
  running a secret scan (gitleaks). Explicitly excludes the Atlas-benchmark gate (dropped per
  product direction).

## Summary of resolved unknowns

All Technical Context fields in `plan.md` are resolved from the existing codebase (no
`NEEDS CLARIFICATION` markers remain in Technical Context). The two spec-level clarifications
(distribution mechanism, auth necessity) were resolved by the user before this phase.
