# Decision Memory Assistant Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first application that ingests project documents, extracts correctable decisions, answers questions with exact citations, displays supersession timelines, and measures hybrid retrieval quality.

**Architecture:** A React/TypeScript frontend calls a single-worker FastAPI modular monolith. PostgreSQL with pgvector stores versioned documents, passages, decisions, traces, and evaluations; Ollama is accessed only through generation and embedding provider interfaces. Implementation proceeds test-first and establishes a Markdown vertical slice before adding PDF/DOCX parsing and the complete UI.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic, PostgreSQL 16, pgvector, httpx, pypdf, python-docx, pytest, React 19, TypeScript, Vite, React Router, Vitest, Testing Library, Docker Compose, Ollama.

---

## Planning Rules

- Use `@superpowers:test-driven-development` for every behavior change.
- Use `@superpowers:verification-before-completion` before claiming a task or milestone complete.
- Keep FastAPI at one worker because MVP jobs are in-process background tasks.
- Keep evidence text untrusted and isolated from model instructions.
- Complete P0 tasks in order. Do not begin the optional P1 task until the final P0 verification passes.
- Run backend commands from `api/` and frontend commands from `web/` unless the command explicitly uses Docker Compose.
- Commit after every task using the stated commit message.

## Repository Structure

```text
decision_assistant/
├── .env.example                         # Local configuration contract
├── .gitignore
├── compose.yaml                         # Web, API, PostgreSQL/pgvector, Ollama
├── Makefile                             # Common local commands
├── README.md                            # Setup, architecture, results, limitations
├── api/
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/0001_initial.py
│   ├── src/decision_memory/
│   │   ├── main.py                      # FastAPI composition root
│   │   ├── config.py                    # Pydantic settings
│   │   ├── db.py                        # Async engine/session lifecycle
│   │   ├── errors.py                    # Stable application/API errors
│   │   ├── models.py                    # SQLAlchemy persistence model
│   │   ├── workspace/service.py
│   │   ├── documents/{router,schemas,service}.py
│   │   ├── ingestion/{jobs,parsers,chunking,service}.py
│   │   ├── decisions/{router,schemas,extractor,service}.py
│   │   ├── providers/{base,fakes,ollama}.py
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
│   ├── package.json
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
- Create: `web/package.json`
- Create: `web/Dockerfile`
- Create: `web/vite.config.ts`

- [ ] **Step 1: Write the Compose configuration test**

Create `api/tests/unit/test_project_layout.py`:

```python
from pathlib import Path
import yaml


def test_compose_declares_required_services() -> None:
    compose = yaml.safe_load(Path("../compose.yaml").read_text())
    assert set(compose["services"]) == {"web", "api", "db", "ollama"}
    assert compose["services"]["api"]["command"][-2:] == ["--workers", "1"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/unit/test_project_layout.py -v`  
Expected: FAIL because `compose.yaml` does not exist.

- [ ] **Step 3: Create the minimal project manifests**

Use `pgvector/pgvector:pg16` for `db`, `ollama/ollama` for `ollama`, health checks for both, named volumes for database/model/upload data, and `uvicorn decision_memory.main:app --host 0.0.0.0 --port 8000 --workers 1` for the API. Pin Python and JavaScript dependencies in their lockfiles during installation.

`api/pyproject.toml` must define runtime dependencies for FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy async, asyncpg, Alembic, pgvector, httpx, python-multipart, pypdf, and python-docx; development dependencies include pytest, pytest-asyncio, pytest-cov, and PyYAML.

- [ ] **Step 4: Install dependencies and rerun the test**

Run: `python -m pip install -e '.[dev]'`  
Run: `python -m pytest tests/unit/test_project_layout.py -v`  
Expected: PASS.

Run: `npm install` in `web/`  
Expected: `package-lock.json` created with no install failure.

- [ ] **Step 5: Validate Compose**

Run: `docker compose config --quiet`  
Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .env.example compose.yaml Makefile api web/package-lock.json
git commit -m "chore: scaffold local decision memory runtime"
```

### Task 2: Create the FastAPI Composition Root and Error Contract (1.5 hours)

**Files:**
- Create: `api/src/decision_memory/__init__.py`
- Create: `api/src/decision_memory/main.py`
- Create: `api/src/decision_memory/config.py`
- Create: `api/src/decision_memory/errors.py`
- Test: `api/tests/unit/test_app.py`

- [ ] **Step 1: Write failing health and error tests**

```python
from fastapi.testclient import TestClient
from decision_memory.main import create_app


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

Run: `pytest tests/unit/test_app.py -v`  
Expected: FAIL because `decision_memory.main` is missing.

- [ ] **Step 3: Implement settings, request IDs, health, and exception handlers**

`Settings` must load database URL, upload directory, Ollama base URL, generation model, embedding model, embedding dimension, upload size limit, timeout, and retry count from environment variables. `create_app()` adds a request-ID middleware, `/health`, CORS for the configured local frontend origin, and handlers returning:

```json
{"code":"not_found","message":"Not found","request_id":"...","retryable":false,"details":null}
```

- [ ] **Step 4: Verify passing behavior**

Run: `pytest tests/unit/test_app.py -v`  
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory api/tests/unit/test_app.py
git commit -m "feat: add API composition root and error contract"
```

### Task 3: Define Provider Interfaces, Fakes, and Ollama Adapters (2 hours)

**Files:**
- Create: `api/src/decision_memory/providers/base.py`
- Create: `api/src/decision_memory/providers/fakes.py`
- Create: `api/src/decision_memory/providers/ollama.py`
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

Run: `pytest tests/unit/test_provider_fakes.py -v`  
Expected: FAIL because provider modules are missing.

- [ ] **Step 3: Implement provider protocols and deterministic fakes**

Define typed `EmbeddingProfile`, `EmbeddingProvider.embed(texts)`, and `GenerationProvider.generate(prompt, response_model)`. Fakes must support queued structured responses and injected failures without network access.

- [ ] **Step 4: Implement Ollama adapters with bounded retries**

Use `httpx.AsyncClient` against `/api/embed` and `/api/chat`, request JSON/schema output, set temperature zero, validate through the supplied Pydantic model, retry transient HTTP errors only, and raise stable provider errors.

- [ ] **Step 5: Run unit and opt-in contract tests**

Run: `pytest tests/unit/test_provider_fakes.py -v`  
Expected: PASS.

Run: `OLLAMA_CONTRACT_TESTS=1 pytest tests/contract/test_ollama_provider.py -v` with Ollama available.  
Expected: PASS; without the environment flag, tests SKIP.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_memory/providers api/tests/unit/test_provider_fakes.py api/tests/contract/test_ollama_provider.py
git commit -m "feat: add model provider contracts and Ollama adapters"
```

### Task 4: Add the Versioned PostgreSQL Schema (2.5 hours)

**Files:**
- Create: `api/src/decision_memory/db.py`
- Create: `api/src/decision_memory/models.py`
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

Run: `docker compose up -d db`  
Run: `pytest tests/integration/test_schema.py -v`  
Expected: FAIL because models/migration are missing.

- [ ] **Step 3: Implement models and migration**

Create all P0 entities from the spec: workspace, document, document version, passage, decision, decision evidence, decision relation, decision revision, ingestion job, retrieval trace, evaluation question/run/result. Add enum/check constraints, foreign keys, cascade rules, timestamps, unique `(document_id, version_number)`, a partial unique active-version index, GIN full-text index, and HNSW/IVFFlat pgvector index supported by the selected local PostgreSQL image.

- [ ] **Step 4: Apply migration and verify**

Run: `alembic upgrade head`  
Run: `pytest tests/integration/test_schema.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory/db.py api/src/decision_memory/models.py api/alembic.ini api/alembic api/tests/conftest.py api/tests/integration/test_schema.py
git commit -m "feat: add versioned decision memory schema"
```

### Task 5: Parse Markdown and Text with Stable Locators (1.5 hours)

**Files:**
- Create: `api/src/decision_memory/ingestion/parsers.py`
- Create: `api/src/decision_memory/ingestion/chunking.py`
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

Run: `pytest tests/unit/test_text_parsers.py tests/unit/test_chunking.py -v`  
Expected: FAIL because parsers are missing.

- [ ] **Step 3: Implement normalized blocks and boundary-aware chunking**

Define `ParsedBlock`, `ParsedDocument`, and `PassageDraft`. Normalize line endings and whitespace conservatively. Chunk on headings/paragraphs, cap passages by configurable character count, add bounded overlap, and hash normalized content with SHA-256.

- [ ] **Step 4: Verify passing behavior**

Run: `pytest tests/unit/test_text_parsers.py tests/unit/test_chunking.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory/ingestion api/tests/unit api/tests/fixtures/meeting.md
git commit -m "feat: parse and chunk text documents with stable locators"
```

### Task 6: Implement Decision Extraction and Evidence Alignment (2 hours)

**Files:**
- Create: `api/src/decision_memory/decisions/schemas.py`
- Create: `api/src/decision_memory/decisions/extractor.py`
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

Run: `pytest tests/unit/test_decision_extractor.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement schema-constrained extraction**

Create decision/status/relation Pydantic schemas, delimit passages as untrusted evidence, prohibit following source instructions, and align each evidence quote to an exact passage substring. Return offsets and content hash; reject invalid statuses, impossible dates, or unaligned evidence after one repair attempt.

- [ ] **Step 4: Verify passing behavior**

Run: `pytest tests/unit/test_decision_extractor.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory/decisions api/tests/unit/test_decision_extractor.py
git commit -m "feat: extract decisions with aligned evidence"
```

### Task 7: Build Transactional, Version-Safe Ingestion (3 hours)

**Files:**
- Create: `api/src/decision_memory/ingestion/service.py`
- Create: `api/src/decision_memory/ingestion/jobs.py`
- Create: `api/src/decision_memory/ingestion/metadata.py`
- Create: `api/src/decision_memory/workspace/service.py`
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

Run: `pytest tests/unit/test_metadata_extractor.py tests/integration/test_ingestion_service.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement the staged pipeline**

Persist an ingestion job, stage immutable version/file metadata, parse the document, and run a metadata extractor that prefers deterministic front matter/headings before schema-constrained generation for missing title/date/participants/source type/project fields. Then chunk/embed/extract, save passages and decisions, and activate inside one transaction. On exception, roll back activation, mark the staged version/job failed with stable code, and leave the old active version untouched. Add startup recovery that marks stale running jobs `interrupted`.

- [ ] **Step 4: Verify passing behavior**

Run: `pytest tests/unit/test_metadata_extractor.py tests/integration/test_ingestion_service.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory/ingestion api/src/decision_memory/workspace api/tests/unit/test_metadata_extractor.py api/tests/integration/test_ingestion_service.py
git commit -m "feat: add transactional version-safe ingestion"
```

### Task 8: Expose Document Upload and Status APIs (2 hours)

**Files:**
- Create: `api/src/decision_memory/documents/schemas.py`
- Create: `api/src/decision_memory/documents/service.py`
- Create: `api/src/decision_memory/documents/router.py`
- Modify: `api/src/decision_memory/main.py`
- Test: `api/tests/integration/test_documents_api.py`

- [ ] **Step 1: Write failing API tests**

Test one and multiple valid uploads returning `202`, invalid extension returning `unsupported_file_type`, excessive size returning `file_too_large`, listing status/progress/errors, document detail with passages, and re-index retry. A mixed multi-file request rejects only invalid files and returns one result object per submitted file.

- [ ] **Step 2: Verify failure**

Run: `pytest tests/integration/test_documents_api.py -v`  
Expected: FAIL with missing routes.

- [ ] **Step 3: Implement upload safety and background dispatch**

Sanitize display names, generate storage names, validate extension plus media type, enforce streaming size limit, store under the configured upload directory, and schedule the ingestion service through `BackgroundTasks`. Return job/document IDs and request ID without waiting for model calls.

- [ ] **Step 4: Verify API behavior**

Run: `pytest tests/integration/test_documents_api.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory/documents api/src/decision_memory/main.py api/tests/integration/test_documents_api.py
git commit -m "feat: add document upload and indexing status API"
```

### Task 9: Implement Hybrid Retrieval, RRF, and Traces (3 hours)

**Files:**
- Create: `api/src/decision_memory/retrieval/schemas.py`
- Create: `api/src/decision_memory/retrieval/rrf.py`
- Create: `api/src/decision_memory/retrieval/repository.py`
- Create: `api/src/decision_memory/retrieval/service.py`
- Create: `api/src/decision_memory/retrieval/router.py`
- Modify: `api/src/decision_memory/main.py`
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

Seed active and retired versions. Assert only active passages appear; explicit person/date/project/document-type filters apply before ranking; semantic and English FTS each return top 20; hybrid trace stores both lists, fused scores, selected evidence, settings, and timings. Add an API assertion that `GET /retrieval-traces/{id}` returns the stored trace and an unknown ID returns the stable `not_found` error.

- [ ] **Step 3: Verify failure**

Run: `pytest tests/unit/test_rrf.py tests/integration/test_hybrid_retrieval.py -v`  
Expected: FAIL.

- [ ] **Step 4: Implement query analysis, repositories, RRF, and trace persistence**

Use deterministic extraction for explicit filters first; use a structured generation call only for intent facets that cannot alter restrictive filters. Search passage vectors, English `tsvector`, and structured decision fields; merge by passage ID and add bounded neighbors after fusion. Register the retrieval router in `create_app()` and expose both the internal search endpoint used by tests and `GET /retrieval-traces/{id}` used by the Ask developer panel.

- [ ] **Step 5: Verify passing behavior**

Run: `pytest tests/unit/test_rrf.py tests/integration/test_hybrid_retrieval.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_memory/retrieval api/src/decision_memory/main.py api/tests/unit/test_rrf.py api/tests/integration/test_hybrid_retrieval.py
git commit -m "feat: add traceable hybrid retrieval"
```

### Task 10: Generate, Verify, and Abstain from Answers (3 hours)

**Files:**
- Create: `api/src/decision_memory/answering/schemas.py`
- Create: `api/src/decision_memory/answering/verifier.py`
- Create: `api/src/decision_memory/answering/service.py`
- Create: `api/src/decision_memory/answering/router.py`
- Modify: `api/src/decision_memory/main.py`
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

Run: `pytest tests/unit/test_answer_verifier.py tests/integration/test_questions_api.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement the answer contract and evidence-pack builder**

Represent answer, atomic claims, citations, conflicts, unsupported facets, and confidence category in Pydantic. The prompt contains only the question and delimited active evidence. Exclude unsupported/needs-review fields and instruct the model to cite passage IDs supplied by the application.

- [ ] **Step 4: Implement deterministic verification and response states**

Validate passage existence/version, quote substring, offsets, hash, claim citations, and explicit entity/date presence. If central support is absent, return `abstained`; if some facets lack support, return `partial`; if active evidence conflicts, return `conflicted` with both citations.

- [ ] **Step 5: Verify passing behavior**

Run: `pytest tests/unit/test_answer_verifier.py tests/integration/test_questions_api.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit the first complete backend vertical slice**

```bash
git add api/src/decision_memory/answering api/src/decision_memory/main.py api/tests
git commit -m "feat: answer questions with verified evidence"
```

**Vertical-slice checkpoint:** Upload the Markdown fixture, wait for indexing with fake providers, ask a supported and unsupported question, and inspect the stored trace. Do not continue until this path is green.

### Task 11: Add PDF and DOCX Parsing (2 hours)

**Files:**
- Modify: `api/src/decision_memory/ingestion/parsers.py`
- Create: `api/tests/unit/test_pdf_parser.py`
- Create: `api/tests/unit/test_docx_parser.py`
- Create: `api/tests/fixtures/text.pdf`
- Create: `api/tests/fixtures/scanned-empty.pdf`
- Create: `api/tests/fixtures/decision.docx`

- [ ] **Step 1: Write failing format tests**

Assert PDF blocks preserve page numbers, DOCX blocks preserve paragraph ranges, empty/scanned PDF raises `ocr_not_supported`, encrypted PDF raises `pdf_password_protected`, corrupt inputs return parser-specific errors, and DOCX macros/scripts are never executed.

- [ ] **Step 2: Verify failure**

Run: `pytest tests/unit/test_pdf_parser.py tests/unit/test_docx_parser.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement safe format adapters**

Use pypdf to read embedded text page by page and python-docx to read paragraphs plus linearized table cells. Return the shared `ParsedDocument` model. Do not reconstruct layouts, follow links, execute macros, or invoke OCR.

- [ ] **Step 4: Verify all parser tests**

Run: `pytest tests/unit/test_text_parsers.py tests/unit/test_pdf_parser.py tests/unit/test_docx_parser.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory/ingestion/parsers.py api/tests/unit/test_pdf_parser.py api/tests/unit/test_docx_parser.py api/tests/fixtures
git commit -m "feat: ingest PDF and DOCX sources safely"
```

### Task 12: Add Decision Correction and Relationship APIs (2.5 hours)

**Files:**
- Create: `api/src/decision_memory/decisions/service.py`
- Create: `api/src/decision_memory/decisions/router.py`
- Modify: `api/src/decision_memory/decisions/schemas.py`
- Modify: `api/src/decision_memory/main.py`
- Test: `api/tests/integration/test_decisions_api.py`

- [ ] **Step 1: Write failing correction tests**

Test list/detail filters, supported correction with active evidence, unsupported correction without evidence, rejection of retired/stale evidence, revision audit record, explicit `supersedes`, and re-index transition to `needs_review`.

- [ ] **Step 2: Make relationship authority explicit**

Encode this P0 rule in the test: user-confirmed `supersedes` is authoritative domain input and does not require source evidence, but the API stores an optional rationale and never presents the relationship itself as a quoted source fact.

- [ ] **Step 3: Verify failure**

Run: `pytest tests/integration/test_decisions_api.py -v`  
Expected: FAIL.

- [ ] **Step 4: Implement correction/revision/relationship services and routes**

Patch only allowed fields, create one field-level revision per changed field, replace that field's current evidence associations, calculate aggregate review state, and keep source passages immutable. Exclude unsupported fields through the existing evidence-pack query.

- [ ] **Step 5: Verify passing behavior**

Run: `pytest tests/integration/test_decisions_api.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_memory/decisions api/src/decision_memory/main.py api/tests/integration/test_decisions_api.py
git commit -m "feat: add evidence-safe decision corrections"
```

### Task 13: Build Deterministic Decision Timelines (1.5 hours)

**Files:**
- Create: `api/src/decision_memory/timelines/schemas.py`
- Create: `api/src/decision_memory/timelines/service.py`
- Create: `api/src/decision_memory/timelines/router.py`
- Modify: `api/src/decision_memory/main.py`
- Test: `api/tests/unit/test_timeline_service.py`
- Test: `api/tests/integration/test_timelines_api.py`

- [ ] **Step 1: Write failing timeline tests**

Assert chronological ordering, fallback document dates interleaved with known decision dates, both dates missing sorted last, fallback dates explicitly labeled, evidence on every authoritative entry, unconfirmed inferred relation labeled `possible_revision`, user-confirmed supersession changing display state, and unsupported/needs-review corrections excluded.

- [ ] **Step 2: Verify failure**

Run: `pytest tests/unit/test_timeline_service.py tests/integration/test_timelines_api.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement topic matching and deterministic relation expansion**

Use normalized topic equality plus hybrid candidate IDs and expand stored relations. Compute `sort_date = effective_date or document_date`; sort dated entries together by `(sort_date, created_at)`, then place entries lacking both dates last by `created_at`. Return `date_is_fallback` so the UI distinguishes a document-date fallback, and return evidence-bearing DTOs with authoritative versus possible labels.

- [ ] **Step 4: Verify passing behavior**

Run: `pytest tests/unit/test_timeline_service.py tests/integration/test_timelines_api.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/decision_memory/timelines api/src/decision_memory/main.py api/tests/unit/test_timeline_service.py api/tests/integration/test_timelines_api.py
git commit -m "feat: add cited decision timelines"
```

### Task 14: Implement Evaluation Metrics and Run Lifecycle (2.5 hours)

**Files:**
- Create: `api/src/decision_memory/evaluation/schemas.py`
- Create: `api/src/decision_memory/evaluation/metrics.py`
- Create: `api/src/decision_memory/evaluation/service.py`
- Create: `api/src/decision_memory/evaluation/router.py`
- Modify: `api/src/decision_memory/main.py`
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

Run: `pytest tests/unit/test_evaluation_metrics.py tests/integration/test_evaluation_runs.py -v`  
Expected: FAIL.

- [ ] **Step 4: Implement metrics and background run service**

Load versioned JSON fixtures, execute each question through the selected retrieval strategy, store all raw results, calculate aggregates, and use a fixed temperature-zero judge prompt for claim support. Keep structural citation validity separate from gold citation relevance.

- [ ] **Step 5: Verify passing behavior**

Run: `pytest tests/unit/test_evaluation_metrics.py tests/integration/test_evaluation_runs.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/decision_memory/evaluation api/src/decision_memory/main.py api/tests
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

- [ ] **Step 1: Write the failing navigation/error test**

```tsx
it("renders all primary navigation destinations", () => {
  render(<App />);
  for (const label of ["Workspace", "Ask", "Timeline", "Evaluation"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
});
```

- [ ] **Step 2: Verify failure**

Run: `npm test -- --run src/app/App.test.tsx`  
Expected: FAIL because the app is missing.

- [ ] **Step 3: Implement the shell, routes, typed client, and error boundary**

Create routes for `/`, `/ask`, `/timeline`, `/decisions/:id`, and `/evaluation`. The client parses the stable API error shape and preserves request IDs. Use accessible semantic navigation and responsive CSS; do not add a component framework.

- [ ] **Step 4: Verify passing behavior**

Run: `npm test -- --run src/app/App.test.tsx`  
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

Run: `npm test -- --run src/pages/Workspace.test.tsx`  
Expected: FAIL.

- [ ] **Step 3: Implement upload/list/detail/status behavior**

Use a 2-second poll only while jobs are non-terminal; stop polling after completed/failed or component unmount. Display extracted title/date/participants/source type/project, modification state, and decision count returned by the document API. Display `.md, .txt, .pdf, .docx` help and explicit OCR/password/corruption limitations.

- [ ] **Step 4: Verify passing behavior**

Run: `npm test -- --run src/pages/Workspace.test.tsx`  
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

Run: `npm test -- --run src/pages/Ask.test.tsx`  
Expected: FAIL.

- [ ] **Step 3: Implement the question and evidence experience**

Render model output only through typed fields, never raw HTML. Number citations consistently across claims, show unsupported facets beside the answer, and load a trace by trace ID only when expanded.

- [ ] **Step 4: Verify passing behavior**

Run: `npm test -- --run src/pages/Ask.test.tsx`  
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

Run: `npm test -- --run src/pages/DecisionDetail.test.tsx src/pages/Timeline.test.tsx`  
Expected: FAIL.

- [ ] **Step 3: Implement both screens**

Require explicit confirmation before saving unsupported corrections. Display user-confirmed relationships as domain input, not quoted facts. Keep the timeline accessible as an ordered list with status text in addition to color.

- [ ] **Step 4: Verify passing behavior**

Run: `npm test -- --run src/pages/DecisionDetail.test.tsx src/pages/Timeline.test.tsx`  
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

Run: `npm test -- --run src/pages/Evaluation.test.tsx`  
Expected: FAIL.

- [ ] **Step 3: Implement the dashboard**

Present semantic and hybrid runs side by side only after both use the same dataset/model configuration; otherwise show a configuration mismatch warning. Link each failed metric row to stored diagnostics.

- [ ] **Step 4: Verify passing behavior**

Run: `npm test -- --run src/pages/Evaluation.test.tsx`  
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

Run: `pytest tests/unit/test_evaluation_fixture.py -v`  
Expected: FAIL because fixtures are absent.

- [ ] **Step 3: Write one internally consistent fictional project history**

The documents must contain exact, recoverable evidence for proposed June authentication, May postponement, Priya ownership, authorization-audit reason, July internal beta revision, public rollout remaining postponed, one deliberately conflicting owner/status statement, unrelated decisions, and unsupported topics. Generate DOCX/PDF fixtures from reviewed source text and retain the source-generation script or Markdown alongside them for auditability.

- [ ] **Step 4: Author 20 gold questions and validate them**

Each entry includes ID, question, expected atomic claims, expected passage/document locators, expected status, expected answer/abstain facets, and tags. Manually verify every quote/locator after actual ingestion; update gold locators rather than hard-coding database IDs.

- [ ] **Step 5: Verify passing fixtures**

Run: `pytest tests/unit/test_evaluation_fixture.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sample_data evaluation scripts/build_sample_documents.py api/tests/unit/test_evaluation_fixture.py
git commit -m "test: add Atlas project benchmark corpus"
```

### Task 21: Complete Docker Smoke Test, Documentation, and Demo (3 hours)

**Files:**
- Create: `scripts/smoke.sh`
- Create: `README.md`
- Modify: `.env.example`
- Modify: `Makefile`
- Test: all backend/frontend/Compose checks

- [ ] **Step 1: Write the smoke script before running it**

The script must start Compose, wait for health, migrate, upload the two Markdown fixtures containing the earlier and later authentication decisions, poll both to completion, ask the authentication question, and assert a citation. It must then list the two extracted decisions, call `POST /decisions/{id}/relations` to confirm the later decision `supersedes` the earlier one, request the timeline, assert the authoritative superseded event, and exit nonzero on any failure. It may use fake providers in CI and real Ollama in the recorded local demo.

- [ ] **Step 2: Run the complete deterministic test suite**

Run: `pytest -m 'not ollama' --cov=decision_memory --cov-report=term-missing`  
Expected: PASS with no unexpected skip.

Run: `npm test -- --run`  
Expected: PASS.

Run: `npm run build`  
Expected: production frontend build succeeds.

- [ ] **Step 3: Run migration and Compose verification**

Run: `docker compose config --quiet`  
Run: `docker compose build`  
Run: `docker compose up -d`  
Run: `docker compose exec api alembic upgrade head`  
Expected: all services healthy and migration succeeds.

- [ ] **Step 4: Run the smoke test**

Run: `bash scripts/smoke.sh`  
Expected: `SMOKE PASS: upload -> index -> ask -> citation -> timeline`.

- [ ] **Step 5: Run the real local evaluation**

Start Ollama with configured embedding/generation models, ingest the complete Atlas corpus, run semantic-only and hybrid benchmarks, and save actual output through the application. Verify hybrid top-five hit rate is at least 80%; if it is not, debug chunking/query/fusion using traces before tuning thresholds.

- [ ] **Step 6: Finish the README**

Document setup, architecture diagram, module boundaries, provider swapping, data model/versioning, supported formats, security boundaries, evaluation definitions and actual results, trade-offs, limitations, troubleshooting, and the exact 3–5 minute demo flow. Add a manual audit table for all local-judge disagreements in the approximately 20-question dataset, recording question ID, claim, judge result, human result, and resolution. Do not report invented metrics.

- [ ] **Step 7: Final verification and repository audit**

Run: `git diff --check`  
Run: `git status --short`  
Expected: no formatting errors; only intended documentation/result changes remain.

- [ ] **Step 8: Commit**

```bash
git add scripts/smoke.sh README.md .env.example Makefile
git commit -m "docs: complete local MVP verification and demo"
```

## P1 Boundary

P1 enhancements are not part of this implementation plan. After P0 verification, any measured enhancement requires its own focused plan containing the failing benchmark/test, exact affected files, and expected metric change. Do not spend the 5.5-hour P0 contingency on speculative P1 work.

## Milestone Checkpoints

1. **Foundation:** Tasks 1–4; Compose, API contracts, providers, and schema are green.
2. **Backend vertical slice:** Tasks 5–10; Markdown upload through verified answer and trace works.
3. **Complete domain:** Tasks 11–14; all formats, corrections, timeline, and evaluation work.
4. **Complete product:** Tasks 15–20; all five screens and benchmark corpus work.
5. **Portfolio handoff:** Task 21; Docker, metrics, README, and demo are verified.

Stop at each checkpoint, run its named tests, and review elapsed time against the 50-hour budget. Omit P1 if the P0 forecast exceeds the remaining budget.

The 21 P0 tasks are budgeted at approximately 44.5 hours, leaving 5.5 hours for integration/debugging contingency inside the 50-hour limit.
