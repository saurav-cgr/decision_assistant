# Phase 1 Contracts: New/Changed API Surface

Existing endpoints (`/documents`, `/evaluation/runs`, `/decisions`, `/retrieval`, `/auth`) are
unchanged in shape; this feature adds status/control endpoints for the new operational entities.
All endpoints stay scoped by `workspace_id` (Constitution II) and JWT-authenticated (R2), except
setup/health endpoints that must be reachable before auth is configured.

## Corpus rebuild status

`GET /workspace/{workspace_id}/corpus-rebuild`

- 200: latest `CorpusRebuild` row for the workspace — `status`, `reason`, `documents_total`,
  `documents_completed`, `started_at`, `error` (sanitized).
- 404: no rebuild has ever run for this workspace.

`POST /workspace/{workspace_id}/corpus-rebuild/retry`

- Only valid when latest rebuild `status == "failed"`. Creates a new `pending` `CorpusRebuild` row.
- 409 if a `pending`/`running` rebuild already exists (single-rebuild-at-a-time invariant).

## Provider disclosure

`GET /workspace/{workspace_id}/provider-disclosure`

- 200: `{ provider, generation_provider, embedding_provider,
  generation_sends_document_text_remotely: bool, embedding_sends_document_text_remotely: bool,
  sends_document_text_remotely: bool, acknowledged_at: timestamp | null }`. `provider` equals
  `generation_provider` and is kept for back-compat. The per-provider names and flags let a mixed
  configuration (e.g. local generation + remote embedding) disclose which provider each half of
  document text goes to.

`POST /workspace/{workspace_id}/provider-disclosure/ack`

- Records `disclosure_acknowledged_at = now()`. Idempotent.
- Upload endpoints (`POST /documents/upload`) return 409 `disclosure_not_acknowledged` if this has
  not been called yet.

## Provider switch confirmation

`POST /workspace/{workspace_id}/provider` (or extends an existing settings endpoint)

- Body: `{ generation_provider, embedding_provider, confirm_rebuild: bool }`.
- If the change alters the embedding/chunking profile and `confirm_rebuild` is not `true`: 409
  with a payload describing the pending rebuild, so the UI can show the confirmation dialog before
  resubmitting with `confirm_rebuild: true`.
- On confirmed switch: updates provider config, then behaves like the automatic
  `corpus_reset_required` detection path (creates a `CorpusRebuild`).

## Diagnostics bundle

`GET /diagnostics/bundle`

- 200, `application/zip`: logs (secret-scrubbed), `alembic current` output, app version, sanitized
  config dump. No workspace scoping needed (host-machine-level, not per-workspace data) but still
  requires authentication.

## First-run setup

`GET /setup/status`

- 200: `{ needs_password_setup: bool, needs_provider_disclosure: bool }`. Reachable without a JWT
  (there is no user yet on a truly fresh install).

`POST /setup/password`

- Body: `{ password }`. Only valid while `needs_password_setup == true`; creates the local user
  and returns a session/JWT. Subsequent calls 409.

## Backup / restore

Not HTTP endpoints — CLI-only (`make backup`, `make restore`, or `scripts/backup.sh` /
`scripts/restore.sh`) per spec FR-008/FR-009, run against the Docker Compose stack from the host,
not exposed over the API. Documented in `quickstart.md` and user docs (FR-027).

## Version endpoint

`GET /health` (existing) gains a `version` field in its response body, so the web UI can render
the app version (FR-024) from data already being fetched.
