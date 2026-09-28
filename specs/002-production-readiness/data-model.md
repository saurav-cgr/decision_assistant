# Phase 1 Data Model: Single-Tenant Local Production Readiness

Scope: only new entities/fields and the corpus/non-corpus table split this feature depends on.
Existing tables not listed here are unchanged.

## Existing tables — classification (from research R5)

| Table | Class | Rebuild behavior |
|---|---|---|
| `documents`, `document_versions`, `passages`, `embedding_cache`, `ingestion_jobs` | Corpus-derived | Deleted (workspace-scoped, not a bare `TRUNCATE` — see DB37/DB34, `TRUNCATE` ignores `ON DELETE SET NULL`) and regenerated from `uploads_data` during a `CorpusRebuild`. Exception (DB42): a document with **no active version** (ingestion failed or never finished) is preserved with its versions, stored-file reference, and `IngestionJob` retry path — it cannot be re-ingested, so deleting it would destroy the only record of it |
| `users`, `workspaces`, `decisions`, `decision_evidence`, `decision_relations`, `decision_revisions`, `conversations`, `conversation_messages`, `question_answers`, `evaluation_questions`, `evaluation_runs`, `evaluation_results`, `retrieval_traces` | Non-derived | Never deleted by `CorpusRebuild`. `decisions.document_version_id` and `decision_evidence.passage_id` are `ON DELETE SET NULL` (revision `0014_decision_setnull_fk`, DB34), so a rebuild severs those two references instead of leaving them "untouched" — the row and its other fields survive unchanged, but the FK reads `NULL` until re-resolved. `decisions.workspace_id` (revision `0015_decisions_workspace_id`, DB38) is denormalized onto the row directly so workspace-scoped listing/lookup survives the same nulling. `retrieval_traces` was originally listed as corpus-derived, but `conversation_messages`/`question_answers` cascade from it (DB37) and it has no FK to `passages`/`document_versions` (only plain JSONB ids), so it is reclassified non-derived and left in place; its contents may reference passage/document-version ids that no longer exist after a rebuild, same class of staleness as `decision_evidence.citation_stale`. |

## New/changed entities

### CorpusRebuild (new table, e.g. `corpus_rebuilds`)

Tracks an automatic background rebuild triggered by `corpus_reset_required`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `workspace_id` | UUID FK → `workspaces.id`, indexed | one active rebuild per workspace (partial unique index on `status = 'running'`) |
| `status` | enum-like string: `pending, running, completed, failed` | mirrors `IngestionJob.status` convention |
| `reason` | string | e.g. `embedding_profile_changed`, `provider_switch` |
| `documents_total` | int | snapshot of documents to reingest |
| `documents_completed` | int | for progress display |
| `error` | JSONB, nullable | sanitized error detail |
| `started_at`, `finished_at` | timestamptz, nullable | |
| `created_at`, `updated_at` | timestamptz | `TimestampMixin` |

State transitions: `pending → running → completed`, or `running → failed` (retryable via a new
`pending` row; old failed row stays as history). Only one `pending`/`running` row per workspace at
a time (spec edge case: no concurrent rebuilds).

A `failed` rebuild is all-or-nothing (DB43): a document that fails to re-ingest (spec.md edge case
— provider unreachable) aborts the whole corpus transaction, which rolls back, so the workspace
keeps the corpus it had before the rebuild (documents, active versions, passages, and every
decision/evidence link) and the `failed` row is the only trace of the attempt. `error` records the
offending document's id and its underlying error code. A retry (`POST
/workspace/{id}/corpus-rebuild/retry`) therefore re-runs against real data rather than against a
corpus the failed attempt had already emptied.

Row lifecycle (DB41): the `CorpusRebuild` row is committed **before** the rebuild's corpus
transaction starts, and every progress change is committed in its own short session, so `GET
/workspaces/{id}/corpus-rebuild` reports `pending`/`running` progress while the rebuild runs. The
corpus work itself stays in one transaction that commits at the end (readers keep seeing the old
corpus throughout). Because the row therefore outlives a crash, startup sweeps `pending`/`running`
rows to `failed` (`rebuild_interrupted`) before dispatching anything new — otherwise the
single-active index would block every later rebuild for that workspace.

### DecisionEvidence — stale-citation flag (extend existing table)

`decision_evidence` rows cite `passage_id`. A corpus rebuild regenerates passages with new IDs, so
existing citations no longer resolve.

| Field | Type | Notes |
|---|---|---|
| `citation_stale` (new column) | boolean, default `false` | set `true` for evidence rows whose `passage_id` no longer exists after a rebuild completes |
| `quote` (new column, revision `0016_evidence_quote`, DB40) | text, nullable | the exact extracted quote, stored instead of derived from `passages.content[start_offset:end_offset]`, so it survives the passage's deletion. NULL only for a row an earlier rebuild already orphaned, or when the source text genuinely changed |

Decision text, `decision_evidence` rows, and their parent `decisions` are never deleted by a
rebuild — only flagged. A rebuild re-resolves what it can (T031): `decisions.document_version_id`
is re-pointed at the rebuilt version of the same (identity-preserved) document, and each evidence
row is re-linked to a new passage — first by identical `content_hash`, then by locating the stored
`quote` inside the rebuilt passages, which is what makes re-chunked (reshaped) evidence survive
rather than only identically-rechunked evidence. Only when neither matches does `passage_id` stay
`NULL` with `citation_stale = true`.

### InstallationSecrets (no new table — file-based)

Not a database entity. `AUTH_JWT_SECRET` and the generated database password are written to a
local `.env` on first run by the setup step (R7). No schema change; `config.py` `Settings` gains
startup validation (reject missing/placeholder values), not new fields.

### BackupArchive (no new table — filesystem entity)

A timestamped directory/tarball on the host filesystem (outside Docker volumes), containing a
`pg_dump` file and an uploads tarball. Not tracked in Postgres — tracking backups in the same
database that might need restoring would be circular. The backup script names files
`decision-assistant-backup-<UTC timestamp>.tar.gz`; restore reads that structure directly.

### DiagnosticsBundle (no new table — generated on demand)

A zip built on request from: rotating log files on disk, `alembic current` output, app version,
and a sanitized dump of `Settings` (secret fields excluded by field-name allowlist, not blocklist,
to fail closed on new secret fields).

### ProviderDisclosureAcknowledgment (extend `workspaces`, or new column)

| Field | Type | Notes |
|---|---|---|
| `disclosure_acknowledged_at` (new column on `workspaces`) | timestamptz, nullable | set when the user acknowledges the first-run provider disclosure (R8); upload endpoints reject with a specific error if null |

### IngestionJob / EvaluationRun — requeue support (extend existing)

`IngestionJob` already has `attempt_count`. No new column required for ingestion; the startup
sweep (R4) increments `attempt_count` and re-dispatches instead of only marking `failed`, capping
at a configured max (new `Settings.max_ingestion_attempts`, default e.g. 3).

`EvaluationRun` (in `evaluation/models.py`) needs the same treatment; check whether it already has
an `attempt_count`-equivalent column during implementation — if not, a small additive migration
adds one, following the `IngestionJob` pattern.

## Migration notes

- New Alembic revision(s) needed: `corpus_rebuilds` table, `decision_evidence.citation_stale`
  column, `decision_evidence.quote` column (revision `0016_evidence_quote`, DB40),
  `workspaces.disclosure_acknowledged_at` column, and (if absent) an attempt-tracking
  column on `evaluation_runs`. All additive — no column drops, no data migration, consistent with
  Constitution II (new revision, `0001_initial.py` untouched).
- No corpus-profile change is introduced by this feature itself, so these migrations do not
  trigger `corpus_reset_required` on their own.
