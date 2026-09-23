# AGENTS.md

## Critical constraints

- **Secrets**: NEVER commit `.env`, local backups, API keys, credentials, or tokens. Use `.env.example` as the only configuration template. `.env.gemini.bak` is a local untracked backup, not a clean source of truth; never stage it. `GEMINI_API_KEY` must never be logged or returned.
- **Corpus contract**: NEVER attempt an in-place corpus migration. Changing embedding or chunking profiles fails with `corpus_reset_required`. Reset PostgreSQL and reingest; this development project provides no legacy-corpus compatibility.
- **Schema migrations**: `api/alembic/versions/0001_initial.py` is the immutable fresh-schema baseline with no `down_revision`. Create a new Alembic revision for every schema change; NEVER edit `0001` or rewrite migration history. Corpus changes use reset/reingestion, not legacy-row backfills.
- **Reset safety**: A corpus reset drops only PostgreSQL and preserves `uploads_data`, `ollama_data`, and `web_node_modules`. NEVER use `docker compose down -v` for a corpus reset. A complete Compose purge is allowed only when the user explicitly requests it and acknowledges that all project volumes will be deleted.
- **Git**: NEVER force push.
- **SQL**: NEVER interpolate or trust user-controlled input. Use SQLAlchemy expressions or bound parameters.
- **Escalation**: Ask before DB schema changes, new dependencies, authorization changes, rerank enablement, destructive database resets, or dropping columns.
- **Plan approval gate (interactive work only)**: For work following an implementation plan *outside a SpecKit loop*, complete only one plan step at a time. After each step, stop and report the files changed, verification performed, and any remaining risks. Ask the user to review. Do not commit, begin the next step, or expand scope until the user explicitly says `continue`. After approval, commit only the approved step, then proceed to the next step. **Inside a `$speckit-loop` context, this gate does not apply.** The maker (Luna High) may iterate autonomously through the loop contract's done-criteria, subject to `max_iterations`. The substitute human gate is `$speckit-loop-guard`, which is the only command that can close the loop.
- **File size**: Keep hand-written source files below 500 lines. Before a file reaches 500 lines, split it along clear responsibilities while preserving behavior and tests. Generated files, lockfiles, fixtures, and immutable migration snapshots are exempt; explain any other unavoidable exception before proceeding.
- **Layering**: Domain rules, persistence, retrieval, evaluation scoring, and provider behavior live in backend Python. React owns presentation, interaction state, accessibility, and client-side display logic; it must not become a second source of domain truth.

## Project overview

Decision-memory assistant: ingest documents → token-budgeted structural chunks → embeddings → hybrid retrieval (RRF plus optional reranker) → schema-constrained answer generation → deterministic verification and abstention. FastAPI monolith backend, React/TypeScript (Vite) frontend, PostgreSQL, and pgvector.

## Build, test, and migration commands

Everything runs through Docker Compose; no host Python, Node, npm, or PostgreSQL is required.

```bash
# API tests
make test-api
docker compose run --rm api pytest tests/unit/test_<file>.py -q

# Web tests and production build
make test-web
docker compose run --rm web npm run build

# Migrations
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic current

## Project shape

```text
api/
  alembic/versions/           Alembic baseline plus additive revisions
  src/decision_assistant/     FastAPI app: providers/, retrieval/, ingestion/,
                              answering/, evaluation/, decisions/, workspace/
  tests/                      unit/, integration/, contract/, fixtures/, support/
web/
  src/api/                    Typed API client
  src/components/             Shared React components
  src/pages/                  Route-level React views
scripts/                      Smoke and deterministic ingestion utilities
sample_data/atlas/            Reproducible development corpus; source of truth
evaluation/questions.json     Versioned Atlas benchmark
```

## Architecture

- **Providers**: `GenerationProvider` and `EmbeddingProvider` protocols. Gemini is default; Ollama is optional. `GenerationRequest` separates trusted `system_instruction` from untrusted `user_content`.
- **Ingestion**: parser → source-neutral `ParsedBlock` (`block_type`, `group_path`, `boundary_before`, locator) → token-budgeted structural chunker (`tiktoken`, `cl100k_base`, offline cache) → embeddings.
- **Retrieval**: semantic search plus passage FTS plus decision FTS → RRF → optional schema-constrained reranker → top-five evidence. The reranker fails open to RRF and is disabled by default.
- **Answering**: evidence pack → generation → `AnswerVerifier` for exact quote, hash, offsets, central claims, and conflicts → answered, partial, conflicted, or abstained response.
- **Conflict detection**: scoped by `decision_id` and field. Independent decision statements do not conflict merely because their text differs.
- **Workspace isolation**: every business query is scoped by `workspace_id`; corpus profiles guard readiness with `corpus_reset_required`.
- **Traces**: `RetrievalTrace` stores candidates, fusion, reranking, timings, and selected-passage metadata. Evaluation runs snapshot their corpus and provider configuration.

## Corpus reset and reingestion

This workflow is destructive to PostgreSQL only. Ask first.

```bash
docker compose stop api web
docker compose exec -T db sh -lc \
  'dropdb --if-exists --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose run --rm api alembic upgrade head
docker compose up -d api web --wait
docker compose run --rm -T api \
  python /workspace/scripts/ingest_corpus.py \
  --api-origin http://api:8000 \
  --source-directory /workspace/sample_data/atlas \
  --workspace-name Atlas
```

Every active `DocumentVersion` must match `CURRENT_CHUNKING_PROFILE`; every passage must have a non-null `embedding_profile`.

## Testing requirements

- **API**: pytest and pytest-asyncio. Fixtures live under `api/tests`; fake providers keep normal tests deterministic.
- **Provider contracts**: `api/tests/contract/` tests are marked `live_provider` and excluded by default. Run them only when live-provider execution is explicitly intended.
- **Web**: Vitest and Testing Library. Cover interaction, error, polling, responsive, and accessibility behavior.
- Mock external services only. Keep provider, prompt, citation, retrieval, and evaluation tests deterministic and offline.
- New behavior needs focused coverage at its owning layer; cross-layer changes need an integration or UI regression.

## Docling PDF parsing (pdf-improvement branch)

- **No runtime downloads**: Docling layout/table artifacts must be predownloaded into `/opt/docling-models` at Docker build time. The runtime must never fetch models over the network. `TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache` has the same rule; apply it to `DOCLING_ARTIFACTS_PATH` as well.
- **Local-only Docling**: Docling must be configured with remote services disabled and English OCR only. No cloud calls, no remote model pulls.
- **Parser contract is reset-required**: Changing `pdf_parser` between `pypdf` and `docling` invalidates the corpus. `resolve_corpus_profile` must include parser name/version and OCR/layout options, and any change must raise `corpus_reset_required`. Do not attempt in-place migration. Default remains `pypdf` during comparison.
- **Unchanged core types**: `parse_document`, `ParsedDocument`, `_SourceBlock`, and the structural chunker signatures are frozen. Docling dispatch happens only inside `_parse_pdf_document`.
- **Locator kinds**: `pypdf` emits `pdf_page`; `docling` emits `pdf_region` (page + normalized bounding box). Page-level gold locators match either kind. Region checks add page-and-bounding-box coverage. Chunk locator aggregation, provenance, API schemas, citation labels, and evaluation matching must all be extended for `pdf_region`.
- **Error mapping**: Docling conversion timeout, OCR failure, and layout failure map to sanitized, non-retryable parse errors. Never surface raw Docling exceptions to API consumers. Docling conversion runs in a worker thread inside the existing ingestion task.
- **PDF UI scope**: The source UI remains an extracted-text viewer in this release. `pdf_region` is stored and returned but not visually highlighted; true visual PDF highlighting is a later feature.
- **Schema migration**: No migration for the parser contract change. It requires explicit PostgreSQL reset and complete reingestion. Ask first before executing the reset.

## Docling fixture set

Fixtures live under `api/tests/fixtures/pdf/`. Do not commit scanned PDFs larger than the repository's existing fixture size budget.

- Digital English PDF (multi-page, single column)
- Multi-column English PDF
- Table-heavy English PDF
- Scanned English PDF (OCR path)
- A page-level gold locator set for citation-matching regression

## Loop sensor gates (before `$speckit-loop-check`)

Before handing an increment to the checker, the maker must run and record output for:

- `make test-api` for touched unit/integration tests
- `docker compose run --rm api alembic upgrade head && alembic current` if any migration was added
- A fixture-based Docling smoke conversion against `sample_data/atlas` (English digital + scanned) if parser code changed
- `docker compose run --rm web npm run build` if any API schema affecting the web client changed

Failures are maker-fixable and must be resolved before the increment is handed off. Do not hand a red increment to the checker; that burns review budget on free errors.

## Parser comparison evaluation

- Run parser comparisons in **separate reset-and-reingest corpora**, one per parser. Never compare under a shared corpus.
- Record results in a versioned artifact at `evaluation/parser_comparison.md` so the decision to promote Docling to default is auditable.
- Compare: retrieval quality, citation validity, abstention and conflict rates, ingest duration, and model/image size. Use `evaluation/questions.json` as the benchmark.
- Docling does not become default until the comparison artifact shows it is at least parity on citation validity and abstention/conflict rates.

## Common gotchas

- `api/tests/conftest.py` creates `decision_assistant_test`. If stale migration state blocks tests, drop only that test database:

  ```bash
  docker compose exec -T db sh -lc \
    'dropdb --if-exists --force -U "$POSTGRES_USER" decision_assistant_test'
  ```

- Running API and web services use bind-mounted source. Restart the affected service after backend changes; rebuild images only for dependency or Dockerfile changes.
- `tiktoken` assets must exist at `TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache`; runtime must not fetch tokenizer assets.
- Rails, Sidekiq, PaperTrail, tenant `CLIENT_NAME`, and Clew-specific instructions do not apply to this repository.
- If local behavior differs from CI, inspect Docker Compose defaults and `.env` override order without printing secret values.

## When to ask vs proceed

**Ask first:** schema migrations, new dependencies, provider/authentication changes, rerank enablement, destructive resets, column drops, or broad architectural rewrites.

**Proceed:** focused tests, documentation, lint fixes, responsive/accessibility fixes, and incremental repairs within files already in scope.

## Reminders

- Recheck staged files for secret leakage before every commit.
- Preserve user changes and unrelated dirty-worktree files.
- Prefer the smallest safe change that satisfies the request.
