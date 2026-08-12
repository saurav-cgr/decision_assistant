# Decision Memory Assistant Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-data-first application that ingests project documents, extracts correctable decisions, answers questions with exact citations, displays supersession timelines, and measures hybrid retrieval quality.

**Architecture:** A React/TypeScript frontend calls a single-worker FastAPI modular monolith. Public business endpoints use a major-version URL namespace beginning at `/api/v1`; infrastructure health and generated OpenAPI documentation remain unversioned. PostgreSQL with pgvector stores versioned documents, passages, decisions, traces, and evaluations. Gemini is the default external generation and embedding provider behind application-owned interfaces; deterministic fakes keep normal tests provider-independent, and Ollama remains an optional adapter rather than a required runtime. Development tools, dependency installation, tests, builds, migrations, and application services run in Docker. The host requires Git, Docker Desktop, network access for live inference, and a user-supplied Gemini API key.

**Tech Stack:** Docker Compose, Python 3.12 container, FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic, PostgreSQL 16, pgvector, Google Gen AI Python SDK, httpx, pypdf, python-docx, pytest, Node.js 24 container, React 19, TypeScript, Vite, React Router, Vitest, and Testing Library. Ollama is retained only as an optional Compose profile/provider adapter.

---

## Planning Rules

- Use `@superpowers:test-driven-development` for every behavior change.
- Use `@superpowers:verification-before-completion` before claiming a task or milestone complete.
- Keep FastAPI at one worker because MVP jobs are in-process background tasks.
- Starting with Task 8A, prefix every public business router with `/api/v1`. Task 8 is the already-completed unversioned RED baseline that Task 8A migrates. Keep `/health`, `/docs`, and `/openapi.json` unversioned. Do not add unversioned compatibility aliases because no external client exists yet; introduce `/api/v2` only for a future breaking public-contract change.
- Keep evidence text untrusted and isolated from model instructions.
- Complete P0 tasks in order. Do not begin the optional P1 task until the final P0 verification passes.
- Run every Python, pytest, Alembic, Node, npm, and Vite command through Docker from the repository root. Do not depend on host Python, Node, npm, PostgreSQL, or Ollama.
- Bind-mount the repository root at `/workspace` in the API development container with workdir `/workspace/api` and `PYTHONPATH=/workspace/api/src`, so imports always resolve live source rather than the package snapshot built into the image. Bind-mount `web/` at `/app` and mount a named `web_node_modules` volume at `/app/node_modules`, so the source mount does not hide image-installed dependencies. This gives API/evaluation commands access to `sample_data/`, `evaluation/`, and `scripts/` without host runtimes or stale code.
- Commit after every task using the stated commit message.
- Never commit `GEMINI_API_KEY`; pass it only to the API container through an ignored `.env` file. Tests and logs must not print it.
- Use deterministic fake providers for the default test suite and backend vertical-slice integration path. Live Gemini contract, smoke, and evaluation commands are opt-in and must fail clearly on missing credentials or exhausted free-tier quota.
- Treat an embedding profile as `(provider, model, dimension, adapter_config_version)`. Never compare vectors from different profiles; a profile change requires re-indexing all active documents.

## Approved Provider Amendment — 2026-08-11

Tasks 1–20 record the implementation sequence already completed with Ollama as the initial adapter. Task 21A migrates the default runtime to Gemini before Task 21's live smoke, evaluation, README, and demo work resumes. Where Task 21's earlier wording conflicts with Task 21A, Task 21A is authoritative.

## Repository Structure

```text
decision_assistant/
├── .env.example                         # Local configuration contract
├── .gitignore
├── compose.yaml                         # Web, API, PostgreSQL; optional Ollama profile
├── Makefile                             # Common local commands
├── README.md                            # Setup, architecture, results, limitations
├── api/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/0001_initial.py
│   ├── src/decision_assistant/
│   │   ├── main.py                      # FastAPI composition root
│   │   ├── config.py                    # Pydantic settings
│   │   ├── db.py                        # Async engine/session lifecycle
│   │   ├── errors.py                    # Stable application/API errors
│   │   ├── models.py                    # SQLAlchemy persistence model
│   │   ├── workspace/service.py
│   │   ├── documents/{router,schemas,service,storage}.py
│   │   ├── ingestion/{jobs,parsers,chunking,service}.py
│   │   ├── decisions/{router,schemas,extractor,service}.py
│   │   ├── providers/{base,fakes,factory,gemini,ollama}.py
│   │   ├── retrieval/{router,schemas,rrf,repository,service}.py
│   │   ├── answering/{router,schemas,verifier,service}.py
│   │   ├── timelines/{router,schemas,service}.py
│   │   └── evaluation/{router,schemas,metrics,service}.py
│   └── tests/
│       ├── unit/                         # Pure deterministic behavior
│       ├── integration/                  # PostgreSQL and API behavior
│       ├── contract/                     # Provider adapters
│       └── fixtures/                     # Small parser/provider fixtures
├── web/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── app/{App,router}.tsx
│   │   ├── api/{client,types}.ts
│   │   ├── components/                   # Shared citations, status, errors
│   │   ├── pages/{Workspace,Ask,Timeline,DecisionDetail,Evaluation}.tsx
│   │   └── test/setup.ts
│   └── src/**/*.test.tsx
├── sample_data/atlas/                    # Fictional project source documents
├── evaluation/questions.json             # Versioned benchmark
└── scripts/smoke.sh                       # Docker end-to-end verification
```

## P0 Implementation Tasks

### Task 1: Scaffold the Local Runtime (1.5 hours)

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `compose.yaml`
- Create: `Makefile`
- Create: `api/pyproject.toml`
- Create: `api/Dockerfile`
- Create: `api/.dockerignore`
- Create: `api/src/decision_assistant/__init__.py`
- Create: `web/package.json`
- Create: `web/Dockerfile`
- Create: `web/.dockerignore`
- Create: `web/vite.config.ts`

- [ ] **Step 1: Run the failing infrastructure check**

Run: `docker compose config --quiet`
Expected: FAIL because `compose.yaml` does not exist.

- [ ] **Step 2: Create the minimal project manifests**

Use `python:3.12-slim` as the API build base, `node:24-bookworm-slim` as the web build/development base, `pgvector/pgvector:pg16` for `db`, and `ollama/ollama` for `ollama`. Add health checks, named volumes for database/model/upload data, the API root bind mount at `/workspace` with workdir `/workspace/api` and `PYTHONPATH=/workspace/api/src`, the web bind mount at `/app`, and named volume `web_node_modules:/app/node_modules`. The web image installs the committed lockfile dependencies so Docker copies them into the initially empty named volume. Run `uvicorn decision_assistant.main:app --host 0.0.0.0 --port 8000 --workers 1` for the API. Configure health-gated `depends_on` conditions for database/model consumers and use an evaluation path such as `/workspace/evaluation/questions.json`. Pass the configured generation and embedding model names to both the API and Ollama services so model-pull commands do not depend on exported host variables. Pin Python dependencies exactly in `pyproject.toml` and commit the npm lockfile.

`api/pyproject.toml` must define runtime dependencies for FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy async, asyncpg, Alembic, pgvector, httpx, python-multipart, pypdf, and python-docx; development dependencies include pytest, pytest-asyncio, and pytest-cov.

- [ ] **Step 3: Validate Compose and generate the frontend lockfile in Docker**

Run: `docker compose config --quiet`
Expected: exit code 0.

Run: `docker run --rm -v "$PWD/web:/app" -w /app node:24-bookworm-slim npm install --package-lock-only`
Expected: `package-lock.json` created with no install failure.

- [ ] **Step 4: Build the development images**

Run: `docker compose build api web`
Expected: both images build successfully using Python 3.12 and Node 24.

- [ ] **Step 5: Verify container toolchains**

Run: `docker compose run --rm api python --version`
Expected: Python 3.12.x.

Run: `docker compose run --rm api pytest --version`
Expected: pytest version printed.

Run: `docker compose run --rm web node --version`
Expected: Node v24.x.

Run: `docker compose run --rm web npm --version`
Expected: npm version printed.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .env.example compose.yaml Makefile api web/package-lock.json
git commit -m "chore: scaffold local decision memory runtime"
```

### Task 2: Create the FastAPI Composition Root and Error Contract (1.5 hours)

**Files:**
- Create: `api/src/decision_assistant/main.py`
- Create: `api/src/decision_assistant/config.py`
- Create: `api/src/decision_assistant/errors.py`
- Test: `api/tests/unit/test_app.py`

- [ ] **Step 1: Write failing health and error tests**

```python
from fastapi.testclient import TestClient
from decision_assistant.main import create_app


def test_health_reports_ready() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_uses_stable_error_shape() -> None:
    response = TestClient(create_app()).get("/missing")
    assert response.status_code == 404
    assert set(response.json()) >= {"code", "message", "request_id", "retryable"}
```

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_app.py -v`
Expected: FAIL because `decision_assistant.main` is missing.

- [ ] **Step 3: Implement settings, request IDs, health, and exception handlers**

`Settings` must load database URL, upload directory, Ollama base URL, generation model, embedding model, embedding dimension, upload size limit, timeout, and retry count from environment variables. `create_app()` adds a request-ID middleware, `/health`, CORS for the configured local frontend origin, and handlers returning:

```json
{"code":"not_found","message":"Not found","request_id":"...","retryable":false,"details":null}
```

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_app.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant api/tests/unit/test_app.py
git commit -m "feat: add API composition root and error contract"
```

### Task 3: Define Provider Interfaces, Fakes, and Ollama Adapters (2 hours)

**Files:**
- Create: `api/src/decision_assistant/providers/base.py`
- Create: `api/src/decision_assistant/providers/fakes.py`
- Create: `api/src/decision_assistant/providers/ollama.py`
- Test: `api/tests/unit/test_provider_fakes.py`
- Test: `api/tests/contract/test_ollama_provider.py`

- [ ] **Step 1: Write failing interface/fake tests**

```python
@pytest.mark.asyncio
async def test_fake_embedding_is_deterministic() -> None:
    provider = FakeEmbeddingProvider(dimension=4)
    assert await provider.embed(["same"]) == await provider.embed(["same"])


@pytest.mark.asyncio
async def test_fake_generation_validates_response_model() -> None:
    provider = FakeGenerationProvider([{"answer": "supported"}])
    result = await provider.generate("prompt", AnswerStub)
    assert result.answer == "supported"
```

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_provider_fakes.py -v`
Expected: FAIL because provider modules are missing.

- [ ] **Step 3: Implement provider protocols and deterministic fakes**

Define typed `EmbeddingProfile`, `EmbeddingProvider.embed(texts)`, and `GenerationProvider.generate(prompt, response_model)`. Fakes must support queued structured responses and injected failures without network access.

- [ ] **Step 4: Implement Ollama adapters with bounded retries**

Use `httpx.AsyncClient` against `/api/embed` and `/api/chat`, request JSON/schema output, set temperature zero, validate through the supplied Pydantic model, retry transient HTTP errors only, and raise stable provider errors.

- [ ] **Step 5: Run unit and opt-in contract tests**

Run: `docker compose run --rm api pytest tests/unit/test_provider_fakes.py -v`
Expected: PASS.

Run: `docker compose up -d ollama --wait`
Run: `docker compose exec ollama sh -lc 'ollama pull "$OLLAMA_GENERATION_MODEL"'`
Run: `docker compose exec ollama sh -lc 'ollama pull "$OLLAMA_EMBEDDING_MODEL"'`
Expected: the Ollama service is healthy and both configured models are available before the contract test.

Run: `docker compose run --rm -e OLLAMA_CONTRACT_TESTS=1 api pytest -m live_provider tests/contract/test_ollama_provider.py -v` with the Ollama service healthy.
Expected: PASS; without the environment flag, tests SKIP.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_assistant/providers api/tests/unit/test_provider_fakes.py api/tests/contract/test_ollama_provider.py
git commit -m "feat: add model provider contracts and Ollama adapters"
```

### Task 4: Add the Versioned PostgreSQL Schema (2.5 hours)

**Files:**
- Create: `api/src/decision_assistant/db.py`
- Create: `api/src/decision_assistant/models.py`
- Create: `api/alembic.ini`
- Create: `api/alembic/env.py`
- Create: `api/alembic/versions/0001_initial.py`
- Create: `api/tests/conftest.py`
- Test: `api/tests/integration/test_schema.py`

- [ ] **Step 1: Write the failing schema invariants test**

```python
@pytest.mark.asyncio
async def test_only_one_document_version_is_active(db_session) -> None:
    document = await make_document(db_session)
    await make_version(db_session, document, number=1, state="active")
    await make_version(db_session, document, number=2, state="active")
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

Also assert that passages require a document-version ID and that pgvector plus the English `tsvector` generated/indexed column are available.

- [ ] **Step 2: Verify failure against the test database**

Run: `docker compose up -d db --wait`
Run: `docker compose run --rm api pytest tests/integration/test_schema.py -v`
Expected: FAIL because models/migration are missing.

- [ ] **Step 3: Implement models and migration**

Create all P0 entities from the spec: workspace, document, document version, passage, decision, decision evidence, decision relation, decision revision, ingestion job, retrieval trace, evaluation question/run/result. Add enum/check constraints, foreign keys, cascade rules, timestamps, unique `(document_id, version_number)`, a partial unique active-version index, GIN full-text index, and HNSW/IVFFlat pgvector index supported by the selected local PostgreSQL image.

- [ ] **Step 4: Apply migration and verify**

Run: `docker compose run --rm api alembic upgrade head`
Run: `docker compose run --rm api pytest tests/integration/test_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/db.py api/src/decision_assistant/models.py api/alembic.ini api/alembic api/tests/conftest.py api/tests/integration/test_schema.py
git commit -m "feat: add versioned decision memory schema"
```

### Task 5: Parse Markdown and Text with Stable Locators (1.5 hours)

**Files:**
- Create: `api/src/decision_assistant/ingestion/parsers.py`
- Create: `api/src/decision_assistant/ingestion/chunking.py`
- Test: `api/tests/unit/test_text_parsers.py`
- Test: `api/tests/unit/test_chunking.py`
- Create: `api/tests/fixtures/meeting.md`

- [ ] **Step 1: Write failing parser tests**

```python
def test_markdown_parser_preserves_line_locator() -> None:
    parsed = parse_document(Path("tests/fixtures/meeting.md"))
    assert parsed.blocks[0].locator == {"kind": "lines", "start": 1, "end": 2}
    assert parsed.blocks[0].text.startswith("Architecture Sync")


def test_chunks_have_reproducible_hashes() -> None:
    first = chunk_document(parse_document(FIXTURE))
    second = chunk_document(parse_document(FIXTURE))
    assert [(x.content, x.content_hash) for x in first] == [
        (x.content, x.content_hash) for x in second
    ]
```

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_text_parsers.py tests/unit/test_chunking.py -v`
Expected: FAIL because parsers are missing.

- [ ] **Step 3: Implement normalized blocks and boundary-aware chunking**

Define `ParsedBlock`, `ParsedDocument`, and `PassageDraft`. Normalize line endings and whitespace conservatively. Chunk on headings/paragraphs, cap passages by configurable character count, add bounded overlap, and hash normalized content with SHA-256.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_text_parsers.py tests/unit/test_chunking.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/ingestion api/tests/unit api/tests/fixtures/meeting.md
git commit -m "feat: parse and chunk text documents with stable locators"
```

### Task 6: Implement Decision Extraction and Evidence Alignment (2 hours)

**Files:**
- Create: `api/src/decision_assistant/decisions/schemas.py`
- Create: `api/src/decision_assistant/decisions/extractor.py`
- Test: `api/tests/unit/test_decision_extractor.py`

- [ ] **Step 1: Write failing extraction tests**

```python
@pytest.mark.asyncio
async def test_extractor_rejects_unaligned_evidence() -> None:
    provider = FakeGenerationProvider([decision_payload(evidence_quote="invented")])
    with pytest.raises(EvidenceAlignmentError):
        await DecisionExtractor(provider).extract([PASSAGE])


@pytest.mark.asyncio
async def test_missing_owner_remains_none() -> None:
    result = await DecisionExtractor(fake_with(owner=None)).extract([PASSAGE])
    assert result[0].owner is None
```

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_decision_extractor.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement schema-constrained extraction**

Create decision/status/relation Pydantic schemas, delimit passages as untrusted evidence, prohibit following source instructions, and align each evidence quote to an exact passage substring. Return offsets and content hash; reject invalid statuses, impossible dates, or unaligned evidence after one repair attempt.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_decision_extractor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/decisions api/tests/unit/test_decision_extractor.py
git commit -m "feat: extract decisions with aligned evidence"
```

### Task 7: Build Transactional, Version-Safe Ingestion (3 hours)

**Files:**
- Create: `api/src/decision_assistant/ingestion/service.py`
- Create: `api/src/decision_assistant/ingestion/jobs.py`
- Create: `api/src/decision_assistant/ingestion/metadata.py`
- Create: `api/src/decision_assistant/workspace/service.py`
- Test: `api/tests/unit/test_metadata_extractor.py`
- Test: `api/tests/integration/test_ingestion_service.py`

- [ ] **Step 1: Write failing version-activation tests**

Cover unchanged checksum skip, successful staging-to-active activation, failed second version preserving first-version searchability, retired extracted decisions, and corrected old decisions becoming `needs_review`.

Write metadata tests that assert deterministic front matter/headings populate title/date/participants/source type/project, missing fields are filled only from a schema-valid fake-generation response, and absent evidence remains null rather than guessed.

```python
@pytest.mark.asyncio
async def test_failed_reindex_keeps_previous_version_active(ingestion_service, document):
    first = await ingestion_service.ingest(document, GOOD_FILE)
    ingestion_service.embedding_provider.fail_next()
    with pytest.raises(ProviderUnavailable):
        await ingestion_service.ingest(document, CHANGED_FILE)
    refreshed = await ingestion_service.get_document(document.id)
    assert refreshed.active_version_id == first.version_id
```

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_metadata_extractor.py tests/integration/test_ingestion_service.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the staged pipeline**

Persist an ingestion job, stage immutable version/file metadata, parse the document, and run a metadata extractor that prefers deterministic front matter/headings before schema-constrained generation for missing title/date/participants/source type/project fields. Then chunk/embed/extract, save passages and decisions, and activate inside one transaction. On exception, roll back activation, mark the staged version/job failed with stable code, and leave the old active version untouched. Add startup recovery that marks stale running jobs `interrupted`.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_metadata_extractor.py tests/integration/test_ingestion_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/ingestion api/src/decision_assistant/workspace api/tests/unit/test_metadata_extractor.py api/tests/integration/test_ingestion_service.py
git commit -m "feat: add transactional version-safe ingestion"
```

### Task 8: Expose Document Upload and Status APIs (2 hours)

**Files:**
- Create: `api/src/decision_assistant/documents/schemas.py`
- Create: `api/src/decision_assistant/documents/service.py`
- Create: `api/src/decision_assistant/documents/router.py`
- Modify: `api/src/decision_assistant/main.py`
- Test: `api/tests/integration/test_documents_api.py`

- [ ] **Step 1: Write failing API tests**

Test one and multiple valid uploads returning `202`, invalid extension returning `unsupported_file_type`, excessive size returning `file_too_large`, listing status/progress/errors, document detail with passages, and re-index retry. A mixed multi-file request rejects only invalid files and returns one result object per submitted file.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/integration/test_documents_api.py -v`
Expected: FAIL with missing routes.

- [ ] **Step 3: Implement upload safety and background dispatch**

Sanitize display names, generate storage names, validate extension plus media type, enforce streaming size limit, store under the configured upload directory, and schedule the ingestion service through `BackgroundTasks`. Return job/document IDs and request ID without waiting for model calls.

- [ ] **Step 4: Verify API behavior**

Run: `docker compose run --rm api pytest tests/integration/test_documents_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/documents api/src/decision_assistant/main.py api/tests/integration/test_documents_api.py
git commit -m "feat: add document upload and indexing status API"
```

### Task 8A: Version the Public API Under `/api/v1` (0.5 hours)

**Files:**
- Modify: `api/src/decision_assistant/documents/router.py`
- Modify: `api/tests/integration/test_documents_api.py`
- Modify: `api/tests/unit/test_app.py`

- [ ] **Step 1: Write failing API namespace tests**

Assert that document operations live under `/api/v1/documents`, the old unversioned `/documents` route returns `404`, `/health` remains available without a version, and generated OpenAPI paths expose only versioned business routes.

```python
def test_public_business_routes_use_v1_namespace() -> None:
    app = create_app()
    client = TestClient(app)
    paths = app.openapi()["paths"]

    assert "/api/v1/documents" in paths
    assert "/documents" not in paths
    assert "/health" in paths
    assert "/api/v1/health" not in paths
    assert all(path == "/health" or path.startswith("/api/v1/") for path in paths)
    assert client.get("/documents").status_code == 404
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
```

- [ ] **Step 2: Verify namespace tests fail**

Run: `docker compose run --rm api pytest tests/unit/test_app.py tests/integration/test_documents_api.py -v`
Expected: FAIL because document routes still use the unversioned `/documents` prefix.

- [ ] **Step 3: Move document routes to the versioned prefix**

Change the documents router prefix to `/api/v1/documents` and update all document API tests. Do not create redirects or duplicate unversioned routes. Keep `/health`, `/docs`, and `/openapi.json` unchanged. Every later business router in this plan must register below `/api/v1`.

- [ ] **Step 4: Verify versioned API behavior and regressions**

Run: `docker compose run --rm api pytest tests/unit tests/integration -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/documents/router.py api/tests/unit/test_app.py api/tests/integration/test_documents_api.py
git commit -m "feat: version public API under v1"
```

### Task 9: Implement Hybrid Retrieval, RRF, and Traces (3 hours)

**Files:**
- Create: `api/src/decision_assistant/retrieval/schemas.py`
- Create: `api/src/decision_assistant/retrieval/rrf.py`
- Create: `api/src/decision_assistant/retrieval/repository.py`
- Create: `api/src/decision_assistant/retrieval/service.py`
- Create: `api/src/decision_assistant/retrieval/router.py`
- Modify: `api/src/decision_assistant/main.py`
- Test: `api/tests/unit/test_rrf.py`
- Test: `api/tests/integration/test_hybrid_retrieval.py`

- [ ] **Step 1: Write the failing RRF test**

```python
def test_rrf_merges_duplicates_and_preserves_rank_sources() -> None:
    fused = reciprocal_rank_fusion(
        {"semantic": ["p2", "p1"], "keyword": ["p1", "p3"]}, k=60
    )
    assert [item.id for item in fused] == ["p1", "p2", "p3"]
    assert fused[0].source_ranks == {"semantic": 2, "keyword": 1}
```

- [ ] **Step 2: Write PostgreSQL retrieval tests**

Seed active and retired versions. Assert only active passages appear; explicit person/date/project/document-type filters apply before ranking; semantic and English FTS each return top 20; hybrid trace stores both lists, fused scores, selected evidence, settings, and timings. Add an API assertion that `GET /api/v1/retrieval-traces/{id}` returns the stored trace and an unknown ID returns the stable `not_found` error.

- [ ] **Step 3: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_rrf.py tests/integration/test_hybrid_retrieval.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement query analysis, repositories, RRF, and trace persistence**

Use deterministic extraction for explicit filters first; use a structured generation call only for intent facets that cannot alter restrictive filters. Search passage vectors, English `tsvector`, and structured decision fields; merge by passage ID and add bounded neighbors after fusion. Register the retrieval router below `/api/v1` in `create_app()` and expose both the internal search endpoint used by tests and `GET /api/v1/retrieval-traces/{id}` used by the Ask developer panel.

- [ ] **Step 5: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_rrf.py tests/integration/test_hybrid_retrieval.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_assistant/retrieval api/src/decision_assistant/main.py api/tests/unit/test_rrf.py api/tests/integration/test_hybrid_retrieval.py
git commit -m "feat: add traceable hybrid retrieval"
```

### Task 10: Generate, Verify, and Abstain from Answers (3 hours)

**Files:**
- Create: `api/src/decision_assistant/answering/schemas.py`
- Create: `api/src/decision_assistant/answering/verifier.py`
- Create: `api/src/decision_assistant/answering/service.py`
- Create: `api/src/decision_assistant/answering/router.py`
- Modify: `api/src/decision_assistant/main.py`
- Test: `api/tests/unit/test_answer_verifier.py`
- Test: `api/tests/integration/test_questions_api.py`

- [ ] **Step 1: Write failing verifier tests**

Cover exact-quote success, unknown passage failure, stale hash failure, wrong offsets, uncited central claim, unsupported corrected field exclusion, conflicting evidence response, partial abstention, and full abstention.

```python
def test_verifier_rejects_stale_citation() -> None:
    citation = Citation(passage_id=PASSAGE.id, quote="approved", content_hash="old")
    result = verifier.verify(answer_with(citation), {PASSAGE.id: PASSAGE})
    assert result.valid is False
    assert result.errors[0].code == "citation_hash_mismatch"
```

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_answer_verifier.py tests/integration/test_questions_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the answer contract and evidence-pack builder**

Represent answer, atomic claims, citations, conflicts, unsupported facets, and confidence category in Pydantic. The prompt contains only the question and delimited active evidence. Exclude unsupported/needs-review fields and instruct the model to cite passage IDs supplied by the application.

- [ ] **Step 4: Implement deterministic verification and response states**

Validate passage existence/version, quote substring, offsets, hash, claim citations, and explicit entity/date presence. If central support is absent, return `abstained`; if some facets lack support, return `partial`; if active evidence conflicts, return `conflicted` with both citations.

- [ ] **Step 5: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_answer_verifier.py tests/integration/test_questions_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit the first complete backend vertical slice**

```bash
git add api/src/decision_assistant/answering api/src/decision_assistant/main.py api/tests
git commit -m "feat: answer questions with verified evidence"
```

**Vertical-slice checkpoint:** Upload the Markdown fixture, wait for indexing with fake providers, ask a supported and unsupported question, and inspect the stored trace. Do not continue until this path is green.

### Task 11: Add PDF and DOCX Parsing (2 hours)

**Files:**
- Modify: `api/src/decision_assistant/ingestion/parsers.py`
- Create: `api/tests/unit/test_pdf_parser.py`
- Create: `api/tests/unit/test_docx_parser.py`
- Create: `api/tests/fixtures/text.pdf`
- Create: `api/tests/fixtures/scanned-empty.pdf`
- Create: `api/tests/fixtures/decision.docx`

- [ ] **Step 1: Write failing format tests**

Assert PDF blocks preserve page numbers, DOCX blocks preserve paragraph ranges, empty/scanned PDF raises `ocr_not_supported`, encrypted PDF raises `pdf_password_protected`, corrupt inputs return parser-specific errors, and DOCX macros/scripts are never executed.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_pdf_parser.py tests/unit/test_docx_parser.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement safe format adapters**

Use pypdf to read embedded text page by page and python-docx to read paragraphs plus linearized table cells. Return the shared `ParsedDocument` model. Do not reconstruct layouts, follow links, execute macros, or invoke OCR.

- [ ] **Step 4: Verify all parser tests**

Run: `docker compose run --rm api pytest tests/unit/test_text_parsers.py tests/unit/test_pdf_parser.py tests/unit/test_docx_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/ingestion/parsers.py api/tests/unit/test_pdf_parser.py api/tests/unit/test_docx_parser.py api/tests/fixtures
git commit -m "feat: ingest PDF and DOCX sources safely"
```

### Task 12: Add Decision Correction and Relationship APIs (2.5 hours)

**Files:**
- Create: `api/src/decision_assistant/decisions/service.py`
- Create: `api/src/decision_assistant/decisions/router.py`
- Modify: `api/src/decision_assistant/decisions/schemas.py`
- Modify: `api/src/decision_assistant/main.py`
- Test: `api/tests/integration/test_decisions_api.py`

- [ ] **Step 1: Write failing correction tests**

Test list/detail filters, supported correction with active evidence, unsupported correction without evidence, rejection of retired/stale evidence, revision audit record, explicit `supersedes`, and re-index transition to `needs_review`.

- [ ] **Step 2: Make relationship authority explicit**

Encode this P0 rule in the test: user-confirmed `supersedes` is authoritative domain input and does not require source evidence, but the API stores an optional rationale and never presents the relationship itself as a quoted source fact.

- [ ] **Step 3: Verify failure**

Run: `docker compose run --rm api pytest tests/integration/test_decisions_api.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement correction/revision/relationship services and routes**

Patch only allowed fields, create one field-level revision per changed field, replace that field's current evidence associations, calculate aggregate review state, and keep source passages immutable. Exclude unsupported fields through the existing evidence-pack query.

- [ ] **Step 5: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/integration/test_decisions_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_assistant/decisions api/src/decision_assistant/main.py api/tests/integration/test_decisions_api.py
git commit -m "feat: add evidence-safe decision corrections"
```

### Task 13: Build Deterministic Decision Timelines (1.5 hours)

**Files:**
- Create: `api/src/decision_assistant/timelines/schemas.py`
- Create: `api/src/decision_assistant/timelines/service.py`
- Create: `api/src/decision_assistant/timelines/router.py`
- Modify: `api/src/decision_assistant/main.py`
- Test: `api/tests/unit/test_timeline_service.py`
- Test: `api/tests/integration/test_timelines_api.py`

- [ ] **Step 1: Write failing timeline tests**

Assert chronological ordering, fallback document dates interleaved with known decision dates, both dates missing sorted last, fallback dates explicitly labeled, evidence on every authoritative entry, unconfirmed inferred relation labeled `possible_revision`, user-confirmed supersession changing display state, and unsupported/needs-review corrections excluded.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_timeline_service.py tests/integration/test_timelines_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement topic matching and deterministic relation expansion**

Use normalized topic equality plus hybrid candidate IDs and expand stored relations. Compute `sort_date = effective_date or document_date`; sort dated entries together by `(sort_date, created_at)`, then place entries lacking both dates last by `created_at`. Return `date_is_fallback` so the UI distinguishes a document-date fallback, and return evidence-bearing DTOs with authoritative versus possible labels.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_timeline_service.py tests/integration/test_timelines_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_assistant/timelines api/src/decision_assistant/main.py api/tests/unit/test_timeline_service.py api/tests/integration/test_timelines_api.py
git commit -m "feat: add cited decision timelines"
```

### Task 14: Implement Evaluation Metrics and Run Lifecycle (2.5 hours)

**Files:**
- Create: `api/src/decision_assistant/evaluation/schemas.py`
- Create: `api/src/decision_assistant/evaluation/metrics.py`
- Create: `api/src/decision_assistant/evaluation/service.py`
- Create: `api/src/decision_assistant/evaluation/router.py`
- Modify: `api/src/decision_assistant/main.py`
- Test: `api/tests/unit/test_evaluation_metrics.py`
- Test: `api/tests/integration/test_evaluation_runs.py`

- [ ] **Step 1: Write failing metric tests**

Use small literal fixtures to assert top-five hit rate, MRR including zero misses, structural/correct citation rates, answer-versus-abstain accuracy, facet-level partial abstention, median/p95 latency, and claim-support aggregation.

```python
def test_mrr_counts_miss_as_zero() -> None:
    assert mean_reciprocal_rank([["gold", "x"], ["x", "y"]], [{"gold"}, {"gold"}]) == 0.5
```

- [ ] **Step 2: Write run-state tests**

Assert `pending → running → completed`, progress counters, isolated per-question failures, failed-run structured error, identical dataset/config snapshots for semantic and hybrid comparison, and persisted judge prompt/profile/output.

- [ ] **Step 3: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_evaluation_metrics.py tests/integration/test_evaluation_runs.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement metrics and background run service**

Load versioned JSON fixtures, execute each question through the selected retrieval strategy, store all raw results, calculate aggregates, and use a fixed temperature-zero judge prompt for claim support. Keep structural citation validity separate from gold citation relevance.

- [ ] **Step 5: Verify passing behavior**

Run: `docker compose run --rm api pytest tests/unit/test_evaluation_metrics.py tests/integration/test_evaluation_runs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_assistant/evaluation api/src/decision_assistant/main.py api/tests
git commit -m "feat: add reproducible evaluation runs"
```

### Task 15: Scaffold the React Application and Shared API Client (1.5 hours)

**Files:**
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/app/App.tsx`
- Create: `web/src/app/router.tsx`
- Create: `web/src/api/client.ts`
- Create: `web/src/api/types.ts`
- Create: `web/src/components/AppShell.tsx`
- Create: `web/src/components/ApiError.tsx`
- Create: `web/src/styles.css`
- Create: `web/src/test/setup.ts`
- Test: `web/src/app/App.test.tsx`
- Test: `web/src/api/client.test.ts`

- [ ] **Step 1: Write the failing navigation/error test**

```tsx
it("renders all primary navigation destinations", () => {
  render(<App />);
  for (const label of ["Workspace", "Ask", "Timeline", "Evaluation"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
});
```

Also mock `fetch` in `web/src/api/client.test.ts` and assert that listing documents targets `/api/v1/documents`. Browser routes remain `/`, `/ask`, `/timeline`, `/decisions/:id`, and `/evaluation` without an API version prefix.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm web npm test -- --run src/app/App.test.tsx src/api/client.test.ts`
Expected: FAIL because the app is missing.

- [ ] **Step 3: Implement the shell, routes, typed client, and error boundary**

Create browser routes for `/`, `/ask`, `/timeline`, `/decisions/:id`, and `/evaluation`. Configure the shared API client with `/api/v1` as the base path for every business request; do not version browser routes. The client parses the stable API error shape and preserves request IDs. Use accessible semantic navigation and responsive CSS; do not add a component framework.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm web npm test -- --run src/app/App.test.tsx src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat: scaffold decision memory web application"
```

### Task 16: Build the Workspace Screen (2 hours)

**Files:**
- Create: `web/src/pages/Workspace.tsx`
- Create: `web/src/components/DocumentTable.tsx`
- Create: `web/src/components/IngestionStatus.tsx`
- Test: `web/src/pages/Workspace.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Test supported file accept list, upload progress, polling pending/running jobs, indexed state, extracted title/date/participants/source type/project, checksum-based unchanged/modified state, extracted decision count, retryable error action, parser-specific error copy, and document-detail link.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm web npm test -- --run src/pages/Workspace.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement upload/list/detail/status behavior**

Use a 2-second poll only while jobs are non-terminal; stop polling after completed/failed or component unmount. Display extracted title/date/participants/source type/project, modification state, and decision count returned by the document API. Display `.md, .txt, .pdf, .docx` help and explicit OCR/password/corruption limitations.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm web npm test -- --run src/pages/Workspace.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Workspace.tsx web/src/components web/src/pages/Workspace.test.tsx
git commit -m "feat: add document workspace screen"
```

### Task 17: Build Ask, Citations, Conflicts, and Retrieval Trace UI (2 hours)

**Files:**
- Create: `web/src/pages/Ask.tsx`
- Create: `web/src/components/CitationList.tsx`
- Create: `web/src/components/RetrievalTrace.tsx`
- Test: `web/src/pages/Ask.test.tsx`

- [ ] **Step 1: Write failing answer-state tests**

Cover supported, partial, abstained, and conflicted answers; exact citation quote and source link; trace collapsed by default; semantic/keyword/fused ranks; request-ID error display.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm web npm test -- --run src/pages/Ask.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement the question and evidence experience**

Render model output only through typed fields, never raw HTML. Number citations consistently across claims, show unsupported facets beside the answer, and load a trace by trace ID only when expanded.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm web npm test -- --run src/pages/Ask.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Ask.tsx web/src/components/CitationList.tsx web/src/components/RetrievalTrace.tsx web/src/pages/Ask.test.tsx
git commit -m "feat: add cited question answering UI"
```

### Task 18: Build Decision Detail and Timeline Screens (2 hours)

**Files:**
- Create: `web/src/pages/DecisionDetail.tsx`
- Create: `web/src/pages/Timeline.tsx`
- Create: `web/src/components/DecisionEditor.tsx`
- Create: `web/src/components/TimelineEvent.tsx`
- Test: `web/src/pages/DecisionDetail.test.tsx`
- Test: `web/src/pages/Timeline.test.tsx`

- [ ] **Step 1: Write failing correction/timeline tests**

Test supported correction with evidence selection, unsupported warning, immutable source quote, basic revision list, confirmed relationship form, possible-revision label, chronological order, and evidence link on every authoritative event.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm web npm test -- --run src/pages/DecisionDetail.test.tsx src/pages/Timeline.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement both screens**

Require explicit confirmation before saving unsupported corrections. Display user-confirmed relationships as domain input, not quoted facts. Keep the timeline accessible as an ordered list with status text in addition to color.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm web npm test -- --run src/pages/DecisionDetail.test.tsx src/pages/Timeline.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/DecisionDetail.tsx web/src/pages/Timeline.tsx web/src/components/DecisionEditor.tsx web/src/components/TimelineEvent.tsx web/src/pages/*.test.tsx
git commit -m "feat: add correction and timeline experiences"
```

### Task 19: Build the Evaluation Dashboard (1.5 hours)

**Files:**
- Create: `web/src/pages/Evaluation.tsx`
- Create: `web/src/components/MetricSummary.tsx`
- Create: `web/src/components/EvaluationResults.tsx`
- Test: `web/src/pages/Evaluation.test.tsx`

- [ ] **Step 1: Write failing evaluation UI tests**

Test starting semantic/hybrid runs, progress polling, aggregate metric definitions, latency units, per-question ranks, citation/abstention failures, and stopped polling after terminal state.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm web npm test -- --run src/pages/Evaluation.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement the dashboard**

Present semantic and hybrid runs side by side only after both use the same dataset/model configuration; otherwise show a configuration mismatch warning. Link each failed metric row to stored diagnostics.

- [ ] **Step 4: Verify passing behavior**

Run: `docker compose run --rm web npm test -- --run src/pages/Evaluation.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Evaluation.tsx web/src/components/MetricSummary.tsx web/src/components/EvaluationResults.tsx web/src/pages/Evaluation.test.tsx
git commit -m "feat: add retrieval evaluation dashboard"
```

### Task 20: Add Sample Project and Curated Benchmark (2 hours)

**Files:**
- Create: `sample_data/atlas/01-product-plan.md`
- Create: `sample_data/atlas/02-architecture-sync.md`
- Create: `sample_data/atlas/03-auth-rollout.docx`
- Create: `sample_data/atlas/04-q3-planning.pdf`
- Create: `sample_data/atlas/05-security-notes.txt`
- Create: `evaluation/questions.json`
- Create: `scripts/build_sample_documents.py`
- Create: `api/tests/unit/test_evaluation_fixture.py`

- [ ] **Step 1: Write the failing fixture validation test**

Assert exactly 20 unique question IDs, at least four abstention cases, at least two conflict cases, multi-part questions, expected source locators, expected statuses, and coverage of authentication supersession.

- [ ] **Step 2: Verify failure**

Run: `docker compose run --rm api pytest tests/unit/test_evaluation_fixture.py -v`
Expected: FAIL because fixtures are absent.

- [ ] **Step 3: Write one internally consistent fictional project history**

The documents must contain exact, recoverable evidence for proposed June authentication, May postponement, Priya ownership, authorization-audit reason, July internal beta revision, public rollout remaining postponed, one deliberately conflicting owner/status statement, unrelated decisions, and unsupported topics. Generate DOCX/PDF fixtures from reviewed source text and retain the source-generation script or Markdown alongside them for auditability.

Run: `docker compose run --rm api python ../scripts/build_sample_documents.py`
Expected: the DOCX and PDF fixtures are generated under `/workspace/sample_data/atlas` without requiring host Python.

- [ ] **Step 4: Author 20 gold questions and validate them**

Each entry includes ID, question, expected atomic claims, expected passage/document locators, expected status, expected answer/abstain facets, and tags. Manually verify every quote/locator after actual ingestion; update gold locators rather than hard-coding database IDs.

- [ ] **Step 5: Verify passing fixtures**

Run: `docker compose run --rm api pytest tests/unit/test_evaluation_fixture.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sample_data evaluation scripts/build_sample_documents.py api/tests/unit/test_evaluation_fixture.py
git commit -m "test: add Atlas project benchmark corpus"
```

### Task 21A: Migrate the Default Model Runtime to Gemini (4.5 hours)

**Files:**
- Modify: `api/pyproject.toml`
- Modify: `api/src/decision_assistant/config.py`
- Modify: `api/src/decision_assistant/models.py`
- Modify: `api/src/decision_assistant/providers/base.py`
- Modify: `api/src/decision_assistant/providers/fakes.py`
- Create: `api/src/decision_assistant/providers/gemini.py`
- Create: `api/src/decision_assistant/providers/factory.py`
- Modify: `api/src/decision_assistant/ingestion/metadata.py`
- Modify: `api/src/decision_assistant/decisions/extractor.py`
- Modify: `api/src/decision_assistant/{documents,retrieval,answering,evaluation}/router.py`
- Modify: `api/src/decision_assistant/ingestion/service.py`
- Modify: `api/src/decision_assistant/retrieval/{repository,service}.py`
- Create: `api/src/decision_assistant/workspace/embedding_migration.py`
- Create: `api/src/decision_assistant/commands/reindex_embeddings.py`
- Create: `api/alembic/versions/0002_passage_embedding_profile.py`
- Create: `api/tests/unit/test_gemini_provider.py`
- Create: `api/tests/unit/test_provider_factory.py`
- Create: `api/tests/contract/test_gemini_provider.py`
- Create: `api/tests/integration/test_embedding_migration.py`
- Create: `api/tests/smoke_app.py`
- Create: `api/tests/support/smoke_provider.py`
- Create: `compose.smoke.yaml`
- Modify: affected provider, ingestion, retrieval, evaluation, health, and smoke tests
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `scripts/smoke.sh`

- [ ] **Step 1: Write failing embedding-purpose and Gemini adapter tests**

Extend the provider contract with an `EmbeddingPurpose` enum containing `DOCUMENT` and `QUERY`, a complete `EmbeddingProfile`, and a `GenerationProfile`. Require every embedding call to declare its purpose. Before implementing it, add tests proving:

- ingestion requests document-purpose embeddings;
- retrieval and semantic evaluation request query-purpose embeddings;
- the Gemini adapter reports profile `{provider: "gemini", model: "gemini-embedding-2", dimension: 768, adapter_config_version: "retrieval-prefix-v1"}`;
- the generation profile records model, Developer API version, pinned SDK version, temperature, JSON-schema mode, and prompt-contract version;
- for `gemini-embedding-2`, document inputs become `title: none | text: ...`, query inputs become `task: search result | query: ...`, and mocked SDK requests omit unsupported `EmbedContentConfig.task_type`;
- requests contain at most 32 embedding inputs, preserve ordering, reject oversize inputs rather than truncate, and split larger application batches deterministically;
- returned vector count/order, finite numeric values, declared profile, and every vector dimension are validated;
- any configured embedding dimension other than the schema's fixed 768 is rejected before a provider call;
- structured generation passes the supplied Pydantic JSON schema and validates the response;
- short-lived 429 responses with a usable retry window, timeouts, and transient 5xx failures receive bounded retries;
- missing/rejected credentials, exhausted quota, unsupported schemas, other 4xx responses, malformed JSON, and schema-invalid output map to distinct sanitized error codes;
- oversize generation input is rejected as `provider_input_too_large`; metadata uses a documented bounded sample and decision extraction splits passages into ordered prompt-budgeted batches rather than relying on adapter truncation;
- neither exceptions nor captured logs contain `GEMINI_API_KEY`.

Mock the Gemini SDK/client in unit tests. No unit test may use the network.
Register one `live_provider` pytest marker and apply it to both Gemini and optional Ollama network contract tests. The deterministic suite excludes that marker rather than accumulating expected skips.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `docker compose run --rm api pytest tests/unit/test_gemini_provider.py tests/unit/test_provider_factory.py tests/unit/test_provider_fakes.py -v`
Expected: FAIL because the Gemini adapter, provider factory, and embedding-purpose contract do not exist.

- [ ] **Step 3: Implement the Gemini adapters and centralized provider factory**

Pin `google-genai==2.13.0` and configure the Gemini Developer API `v1beta`. Add settings:

```text
GENERATION_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_GENERATION_MODEL=gemini-3.1-flash-lite
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
GEMINI_EMBEDDING_DIMENSION=768
GEMINI_EMBEDDING_CONFIG_VERSION=retrieval-prefix-v1
GEMINI_GENERATION_PROMPT_VERSION=gemini-json-v1
GEMINI_EMBEDDING_BATCH_SIZE=32
GEMINI_MAX_PROMPT_CHARACTERS=100000
```

Store the key as `SecretStr | None`. Do not validate it while constructing the application so `/health` and deterministic tests remain available; fail with `provider_configuration_invalid` when a live Gemini provider is requested without a key.

Implement async Gemini generation with temperature zero, JSON response MIME type, the supplied JSON schema, a 100,000-character prompt ceiling, bounded retries, and Pydantic validation. Metadata generation receives an explicit bounded beginning-of-document sample; decision extraction partitions passages into deterministic ordered batches within the ceiling and merges results before evidence alignment. Implement batched embeddings with explicit document/query purpose, a maximum of 32 inputs per provider request, no silent truncation, and 768 output dimensions. For `gemini-embedding-2`, apply the versioned prompt formatting inside the adapter and omit unsupported `task_type` so domain services remain provider-neutral. Preserve input order and reject cardinality, non-finite value, and dimension mismatches. Reject non-768 provider configuration because the MVP database column is fixed `vector(768)`.

Create one provider factory/composition dependency and replace concrete `Ollama*Provider` construction in routers. All domain services continue to receive only `EmbeddingProvider` or `GenerationProvider`.

- [ ] **Step 4: Add atomic embedding-only migration and retrieval gating**

Write failing integration tests proving:

1. every newly created `Passage` stores the provider's validated embedding profile;
2. source upload idempotency remains checksum-based and a provider change does not create a `DocumentVersion`;
3. configured profile, `Workspace.embedding_profile` corpus-active profile, and derived migration-pending state are distinct;
4. an empty corpus is not migration-pending and first successful ingestion initializes the corpus-active profile;
5. retrieval fails with stable code `embedding_reindex_required` when any active passage has a different/missing profile or the non-empty workspace corpus-active profile differs;
6. every vector SQL query joins only active document versions and includes the configured passage-profile predicate;
7. the migration command embeds all snapshotted active passages before one atomic vector/profile cutover;
8. a failed batch or snapshot drift leaves every previous vector/profile unchanged;
9. the workspace advisory lock is held from snapshot through provider calls and cutover, and ingestion acquires the same lock before activation;
10. decisions, evidence, relations, revisions, user corrections, passage IDs, offsets, and hashes are unchanged after migration.

Add a nullable JSONB `Passage.embedding_profile` column through Alembic so existing rows are explicitly detected as legacy/mismatched; application validation requires it for every newly created passage. Implement `python -m decision_assistant.commands.reindex_embeddings`: acquire the workspace guard, snapshot active passage/version identities, request and validate all vectors in bounded batches, then atomically re-verify the snapshot and update active passage vectors/profiles plus `Workspace.embedding_profile`. Abort without writes on any failure or drift. Never create a document version or rewrite source-derived records during this operation.

- [ ] **Step 5: Make Gemini the default Docker runtime**

Pass Gemini configuration only to the API container. Remove the API's required dependency on Ollama and place the Ollama service/model volume behind an optional `ollama` Compose profile. `docker compose up -d --wait` must start only database, API, and web by default.

Keep `/health` as process/database liveness. Add `/ready`: return 200 only when the selected providers' required configuration is present and embedding migration is not pending; return a sanitized 503 without calling the provider otherwise. This checks configuration presence, not remote credential validity. Provider-dependent endpoints/jobs return stable configuration, authentication, rate-limit, quota, schema, unavailable, or invalid-response codes as designed.

Add a test-only Compose override whose API command loads `tests.smoke_app`. It overrides the centralized provider dependency with a prompt-aware deterministic smoke provider for the two fixed Atlas smoke documents; production settings cannot select this provider. `SMOKE_PROVIDER_MODE=fake` runs the complete Compose HTTP flow without network access. `SMOKE_PROVIDER_MODE=gemini` requires a key, uses the production app, and never prints the key. Remove all model pulls.

- [ ] **Step 6: Run unit, migration, and opt-in contract verification**

Run: `docker compose run --rm api pytest -m 'not live_provider' -v`
Expected: PASS without a Gemini key or network access.

Run: `SMOKE_PROVIDER_MODE=fake bash scripts/smoke.sh`
Expected: deterministic Compose `upload -> index -> ask -> citation -> timeline` passes through the real API/database layers and mocked provider boundary.

Run: `docker compose up -d db --wait`
Run: `docker compose run --rm api alembic upgrade head`
Expected: migration succeeds against both a fresh database and the existing development database.

Run: `docker compose run --rm -e GEMINI_CONTRACT_TESTS=1 api pytest -m live_provider tests/contract/test_gemini_provider.py -v`
Expected: with `GEMINI_API_KEY` supplied to Compose, generation returns schema-valid output and embedding returns exactly 768 finite values; without the opt-in flag, tests SKIP. Missing credentials or quota exhaustion is skipped/inconclusive, never PASS.

- [ ] **Step 7: Commit**

```bash
git add api compose.yaml .env.example scripts/smoke.sh
git commit -m "feat: use Gemini model providers by default"
```

### Task 21: Complete Docker Smoke Test, Documentation, and Demo (3 hours)

**Files:**
- Create: `scripts/smoke.sh`
- Create: `scripts/smoke.py`
- Create: `README.md`
- Modify: `.env.example`
- Modify: `Makefile`
- Test: all backend/frontend/Compose checks

- [ ] **Step 1: Write the smoke script before running it**

`scripts/smoke.sh` must use only shell built-ins plus Docker Compose. It starts the database, applies migrations, starts API/web, and runs `scripts/smoke.py` from the API container. Fake mode adds `compose.smoke.yaml` and requires no network/key. Gemini mode uses the production app, checks for a key without printing it, and preflights `/ready`. `scripts/smoke.py` uses Python's standard HTTP/JSON libraries from inside the Compose network; it must not require host `curl`, `jq`, Python, Node, or Ollama.

Define one `/api/v1` base constant in `scripts/smoke.py`. Upload the two Markdown fixtures sequentially for deterministic fake response ordering, poll through `/api/v1/documents/{id}`, call `POST /api/v1/questions`, list `/api/v1/decisions`, confirm the later decision `supersedes` the earlier one, and request `/api/v1/timelines?topic=authentication`. Assert a citation and authoritative superseded event. Fake mode is the deterministic CI Compose smoke; Gemini mode is the live acceptance and recorded demo.

- [ ] **Step 2: Run the complete deterministic test suite**

Run: `docker compose run --rm api pytest -m 'not live_provider' --cov=decision_assistant --cov-report=term-missing`
Expected: PASS with no unexpected skip.

Run: `docker compose run --rm web npm test -- --run`
Expected: PASS.

Run: `docker compose run --rm web npm run build`
Expected: production frontend build succeeds.

- [ ] **Step 3: Run migration and Compose verification**

Run: `docker compose config --quiet`
Run: `docker compose build`
Run: `docker compose up -d db --wait`
Run: `docker compose run --rm api alembic upgrade head`
Run: `docker compose up -d api web --wait`
Expected: all services healthy and migration succeeds.

- [ ] **Step 4: Run deterministic and live smoke acceptance**

Run: `SMOKE_PROVIDER_MODE=fake bash scripts/smoke.sh`
Expected: deterministic `SMOKE PASS: upload -> index -> ask -> citation -> timeline`.

Run: `SMOKE_PROVIDER_MODE=gemini bash scripts/smoke.sh`
Expected: `SMOKE PASS: upload -> index -> ask -> citation -> timeline`.

The live command passes only after the complete real Gemini flow succeeds. Missing credentials or quota exhaustion is reported as skipped/inconclusive and does not satisfy final acceptance.

- [ ] **Step 5: Run the live Gemini evaluation**

Run: `docker compose run --rm -e GEMINI_CONTRACT_TESTS=1 api pytest -m live_provider tests/contract/test_gemini_provider.py -v`
Expected: live Gemini generation and 768-dimensional embedding contracts pass using the uncommitted API key.

Using the containerized application, ingest the complete Atlas corpus, run semantic-only and hybrid benchmarks, and save actual output through the application. Verify hybrid top-five hit rate is at least 80%; if it is not, debug chunking/query/fusion using traces before tuning thresholds.

- [ ] **Step 6: Finish the README**

Document Git and Docker Desktop as the only required host installations, plus the required free-tier Gemini API key and network access for live inference; all Python/Node/database commands must use Compose. Document setup, architecture diagram, module boundaries, provider swapping, embedding-profile migration, data transfer/privacy boundaries, data model/versioning, supported formats, evaluation definitions and actual results, free-tier quota limitations, troubleshooting, and the exact 3–5 minute demo flow. Add a manual audit table for all judge disagreements in the approximately 20-question dataset, recording question ID, claim, judge result, human result, and resolution. Do not report invented metrics.

- [ ] **Step 7: Final verification and repository audit**

Run: `git diff --check`
Run: `git status --short`
Expected: no formatting errors; only intended documentation/result changes remain.

- [ ] **Step 8: Commit**

```bash
git add scripts/smoke.sh scripts/smoke.py README.md .env.example Makefile
git commit -m "docs: complete local MVP verification and demo"
```

## P1 Boundary

P1 enhancements are not part of this implementation plan. After P0 verification, any measured enhancement requires its own focused plan containing the failing benchmark/test, exact affected files, and expected metric change. Do not spend the remaining 1-hour P0 contingency on speculative P1 work.

## Milestone Checkpoints

1. **Foundation:** Tasks 1–4; Compose, API contracts, providers, and schema are green.
2. **Backend vertical slice:** Tasks 5–10; Markdown upload through verified answer and trace works.
3. **Complete domain:** Tasks 11–14; all formats, corrections, timeline, and evaluation work.
4. **Complete product:** Tasks 15–20; all five screens and benchmark corpus work.
5. **Provider migration:** Task 21A; Gemini is the default, embedding spaces are protected, and deterministic tests remain offline.
6. **Portfolio handoff:** Task 21; Docker, metrics, README, and demo are verified.

Stop at each checkpoint, run its named tests, and review elapsed time against the 50-hour budget. Omit P1 if the P0 forecast exceeds the remaining budget.

The original 21 P0 tasks were budgeted at approximately 44.5 hours. The approved Gemini migration adds an estimated 4.5 hours, reducing the original integration/debugging contingency from 5.5 to 1 hour while remaining inside the 50-hour limit.
