# Changelog

Decision Assistant follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version of
record is `project.version` in `api/pyproject.toml`; `version` in `web/package.json` must equal it,
and that same value is what `/health` returns and what the account page displays.
`api/tests/unit/test_release_version.py` enforces the match and the format, so a release cannot ship
with the two applications disagreeing about what version they are.

This project is pre-1.0. While it is, the minor position carries breaking changes; from 1.0.0 the
usual SemVer rules apply.

## Entry format

One section per released version, newest first. Copy this shape:

```markdown
## [X.Y.Z] - YYYY-MM-DD

Corpus rebuild on upgrade: yes — the embedding model changed, so every document is re-indexed once
on the first start after upgrading. Decisions and conversations survive it.

### Added
- ...

### Changed
- ...

### Fixed
- ...
```

`Corpus rebuild on upgrade:` is a required line, not decoration (FR-025). It answers the one question
an operator needs before upgrading, and it must say which of the two it is:

- **yes** — and then *what changes, and what the operator should expect*. A rebuild re-ingests every
  document while decisions and conversations stay readable; on a large corpus it runs for a while.
  See `docs/upgrade.md`.
- **no** — and then *why not*. If you cannot say why not, you are not ready to decide it.

A release triggers a rebuild when it changes anything the corpus profile is computed from
(`ingestion/profiles.py`):

| Profile input | Changed by |
| --- | --- |
| Chunking profile | `CHUNKING_PROFILE_PRESETS` / `DEFAULT_CHUNKING_PROFILE_PRESET` and the structural-chunker algorithm version |
| Embedding profile | `provider`, `model`, `dimension`, adapter config version (Gemini) / `ollama-native-v1` (Ollama) |
| PDF parser profile | the `docling` pin, the resolved `docling-core` version, and the layout/OCR options |

Anything else — a UI change, a retrieval-strategy change, a fix that does not touch the above —
rebuilds nothing. The `retrieval_unit_strategy` and rerank settings affect how passages are *read*,
not how they were written, so they do not require a rebuild.

Adding, changing or removing an Alembic revision does not by itself require a rebuild: migrations
apply automatically on the next start, after the automatic pre-migration backup
(`docs/backup-restore.md`).

## [0.1.0] - 2026-09-26

Corpus rebuild on upgrade: no — this is the initial release, so there is no earlier corpus to
invalidate. An install created at this version keeps its corpus until a release says otherwise.

### Added

- Production Compose stack: no source bind-mounts, loopback-only published ports
  (`api`, `web`, `ollama`), PostgreSQL reachable only on the internal network.
- First-run setup: `make setup` generates the JWT signing secret and database password, and the web
  UI creates the single local user and shows its recovery code once.
- Ingestion that survives interruption: durable ingestion jobs, a startup sweep that requeues or
  fails them, and per-document status, progress and retry.
- Corpus rebuild: a `corpus_reset_required` upgrade path that re-ingests documents while decisions
  and conversations stay readable, with progress, abort-and-retry, and per-document re-linking.
- Backup and restore: `make backup` / `make restore`, plus an automatic pre-migration backup.
- Provider disclosure and switch confirmation, including a fully offline Ollama mode.
- Diagnostics without telemetry: rotating secret-scrubbed logs, an authenticated diagnostics bundle,
  and no metrics or error reporting to any remote service.
- Upload safety: content-type validation, size and page limits, and a killable PDF parse timeout that
  leaves the worker able to process the next job.
