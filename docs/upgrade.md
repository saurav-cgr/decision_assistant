# Upgrading Decision Assistant

Decision Assistant runs migrations and corpus rebuilds for you on startup. You pull the new
version, restart the stack, and the app upgrades itself while its decisions, conversations, and
history stay readable.

```bash
make stop
git pull          # or pull the new image tag
make start
```

`make start` is enough — there is no separate migration or reingest step to remember.

## What happens on startup

`api`'s startup sequence runs these steps in order, before the API serves any traffic
(`api/src/decision_assistant/main.py`'s `lifespan`):

1. **Config validation.** A missing `AUTH_JWT_SECRET` or a placeholder `DATABASE_URL` aborts
   startup with a specific error instead of booting with shared credentials.
2. **Pre-migration backup.** Only when a schema migration is actually pending, the database and
   the uploads volume are archived into `./backups` as
   `decision-assistant-premigration-backup-<UTC timestamp>.tar.gz`. If the backup fails,
   migration does not run.
3. **Schema migration.** `alembic upgrade head`, automatically. A failed migration stops startup.
4. **Interrupted-job recovery.** Ingestion jobs and evaluation runs left `running`/`pending` by a
   crash or a stop are requeued (up to the configured attempt bound — `max_ingestion_attempts` /
   `max_evaluation_attempts` in `Settings`, default 3), or marked `failed` once that bound is
   reached.
5. **Corpus rebuild.** Every workspace whose active corpus no longer matches the configured
   profiles gets a rebuild dispatched as a background task. See below.

Steps 2 and 3 are why an upgrade needs the stack to start once before you use it: `make start`
migrates, and the rebuild is what makes existing documents usable again under a new corpus
profile.

## When a corpus rebuild triggers

The app stores the embedding and chunking profile that produced every active document version and
every passage. On startup it compares those stored profiles with the configured ones and raises
`corpus_reset_required` for a workspace whose active corpus no longer matches
(`api/src/decision_assistant/workspace/embedding_profile.py`).

A rebuild is triggered when any of these changes:

| Change | Setting / source |
|---|---|
| Chunking preset (token budget) | `CHUNKING_PROFILE_PRESET` — `baseline`, `compact`, or `expanded` |
| Retrieval unit strategy | `RETRIEVAL_UNIT_STRATEGY` |
| Embedding provider or model | `EMBEDDING_PROVIDER` and the provider's model settings |
| Parser profile | the bundled Docling version, `docling-core` version, OCR engine, or layout model |

The last row is why a Docling upgrade is a corpus change and not just an image change: the parser
profile is part of the corpus fingerprint, so a new parser version invalidates the corpus on
purpose.

There is **no in-place corpus migration**. A changed profile is always resolved by rebuilding from
the stored files, never by rewriting legacy rows. This is a deliberate product decision
(`AGENTS.md`): the alternative is silent, hard-to-verify corpus drift.

## What a rebuild does

A rebuild re-reads every document from the stored upload files and re-chunks, re-embeds, and
re-links it under the configured profiles:

- **Replaced:** `documents`, `document_versions`, `passages`, `embedding_cache`, `ingestion_jobs`
  for the workspace. These are derived from the files in `uploads_data`.
- **Preserved:** `decisions`, `decision_evidence`, `decision_relations`, `decision_revisions`,
  `conversations`, `conversation_messages`, `question_answers`, and `retrieval_traces`. Decisions
  are never deleted and never re-extracted — a rebuild re-links them to the rebuilt passages.
- **Evidence re-linking:** each evidence row is matched to a rebuilt passage first by identical
  chunk `content_hash`, then by locating its stored quote inside the new passages. Only when
  neither matches does it keep a null `passage_id` with `citation_stale = true`, which the UI shows
  as "no longer available after a corpus rebuild".
- **Documents with no active version are kept** (their ingestion failed or never finished). There
  is nothing to re-ingest, and the document, its stored file, and its retry path are the only
  record of it.

Decisions and conversations stay readable **for the whole rebuild**. The corpus swap commits once,
at the end, so readers see the old corpus until the new one is complete. Progress is reported in a
separate transaction.

## Watching progress

```bash
# TOKEN: a bearer token for the workspace owner
curl -H "Authorization: Bearer $TOKEN" \
  127.0.0.1:8000/api/v1/workspaces/{id}/corpus-rebuild
```

The response reports `status` (`pending`, `running`, `completed`, `failed`), `reason`,
`documents_total`, `documents_completed`, `started_at`, `finished_at`, and `error`. Until a rebuild
has run for that workspace the endpoint answers `404 corpus_rebuild_not_found`. A `pending`/`running`
row left behind by a crash is swept to `failed` (`rebuild_interrupted`) on the next startup, and the
workspace dispatches a fresh rebuild.

The workspace page shows the same progress as a banner above the document list: `n/m documents`
while the rebuild runs, and a **Retry rebuild** action when it fails (the banner stays hidden
while no rebuild has run).

## When a rebuild fails

A rebuild is all-or-nothing. If any document fails to re-ingest — an unreachable or invalid
provider key is the common cause — the whole rebuild aborts and rolls back: the workspace keeps the
corpus it had before, with its decisions and evidence links intact. The row records `failed` plus
the offending document's id and error code, and `/ready` keeps reporting the workspace as not ready
until the corpus matches again.

Fix the cause, then retry:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  127.0.0.1:8000/api/v1/workspaces/{id}/corpus-rebuild/retry
```

A retry re-runs against the intact corpus. It is only accepted while the latest rebuild is
`failed`; a `pending`/`running` one returns `409 corpus_rebuild_not_retryable`.

Two things to know about a failed rebuild:

- Retry the **rebuild**, not an individual document. Retrying one document re-extracts decisions
  and can duplicate a decision that already exists, because document retry is a fresh extraction
  rather than a re-link.
- One document that can never be parsed blocks that workspace's rebuild until the document is
  removed. That is the intended trade: the app refuses to discard the old corpus to make progress.

## Before you upgrade: back up

The automatic pre-migration backup happens only when a migration is pending, and it is the app's
own safety net rather than a replacement for your own backup:

```bash
make backup     # writes decision-assistant-backup-<UTC timestamp>.tar.gz
```

Never run `docker compose down -v` as part of an upgrade. That deletes the volumes holding the
database and the uploaded files, which is exactly the data a rebuild needs.

## Verifying an upgrade

1. `make start`, then confirm `/ready` reports ready:
   `curl 127.0.0.1:8000/ready`.
2. `docker compose logs api | grep "corpus rebuild"` for the dispatch and completion lines.
3. `docker compose logs api | grep "startup recovery"` if the previous run was interrupted.
4. Poll `GET /api/v1/workspaces/{id}/corpus-rebuild` until `completed`, and check
   `documents_completed == documents_total`.
5. Open the decisions list and one conversation from before the upgrade: both must still be there,
   with their evidence quotes intact.
