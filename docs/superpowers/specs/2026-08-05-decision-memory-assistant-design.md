# Decision Memory Assistant — MVP Design

**Date:** 2026-08-05  
**Status:** Approved for implementation planning  
**Delivery budget:** Approximately 50 focused hours  
**Primary objective:** Produce a portfolio-quality AI engineering project that demonstrates architectural judgment, evidence-grounded generation, retrieval evaluation, and local-first operation.

## 1. Product Summary

Decision Memory Assistant converts project notes, specifications, meeting records, PDFs, and Word documents into a searchable history of decisions. A user can ask questions such as:

> Why was authentication postponed, who made that decision, and was it later changed?

The application returns a concise answer, an ordered decision timeline, and citations to exact source passages. It distinguishes supported facts from conflicts and missing evidence instead of filling gaps with model-generated assumptions.

The MVP serves one local workspace and one user. It is designed as a modular monolith so its internal AI capabilities are independently understandable and replaceable without introducing microservice overhead.

## 2. Goals and Success Criteria

### Goals

- Ingest local `.md`, `.txt`, `.pdf`, and `.docx` files.
- Extract inspectable and correctable structured decision records.
- Answer decision-history questions using cited evidence.
- Combine vector and PostgreSQL full-text retrieval.
- Show retrieval traces for learning and debugging.
- Display explicitly linked, chronological decision timelines.
- Evaluate retrieval and answer behavior on approximately 20 curated questions.
- Run locally through Docker Compose with Ollama behind provider interfaces.

### Definition of done

- A clean Docker Compose installation starts the frontend, API, PostgreSQL with pgvector, and Ollama integration.
- Included sample documents can be indexed locally.
- Expected evidence appears in the top five hybrid results for at least 80% of answerable evaluation questions.
- Answers contain citations that resolve to exact stored source passages.
- Conflicting evidence is displayed rather than silently reconciled.
- Unsupported questions produce a full or explicit partial abstention.
- At least one topic demonstrates a correctly ordered supersession timeline.
- The README explains architecture, trade-offs, measured evaluation results, limitations, and local setup.
- A short demo script covers ingestion, extraction correction, questioning, citations, timeline navigation, and evaluation comparison.

## 3. Non-Goals

- Authentication, authorization, or multi-tenancy
- Real-time collaboration
- Slack, Notion, Drive, email, or other hosted integrations
- Audio transcription or meeting recording
- OCR for image-only or scanned PDFs
- Legacy binary `.doc` ingestion
- Password-protected or corrupted document recovery
- Autonomous task execution
- Fine-tuning or training
- Knowledge graphs
- Production-scale permissions or operations
- Native mobile applications
- Redis, Celery, Kafka, or a separate job service

Image-only PDFs are rejected with an `ocr_not_supported` error. Password-protected and corrupted files receive explicit ingestion errors.

## 4. Architectural Approach

### 4.1 Deployment topology

Docker Compose runs four components:

1. **Web:** React and TypeScript single-page application.
2. **API:** Python and FastAPI modular monolith, running as one worker for the MVP.
3. **Database:** PostgreSQL with the pgvector extension.
4. **Model runtime:** Ollama for local generation and embeddings.

Uploaded source files and database data use local Docker volumes. The browser communicates only with FastAPI. FastAPI owns ingestion orchestration, domain rules, retrieval, answer construction, evaluation, and provider calls.

### 4.2 Backend modules

The API is divided into modules with explicit contracts:

- `workspace`: the single workspace and application configuration.
- `documents`: upload validation, persistence, metadata, source rendering, and ingestion status.
- `ingestion`: parsing, normalization, chunking, change detection, background execution, and retries.
- `decisions`: extraction, validation, manual correction, evidence associations, and decision relationships.
- `retrieval`: query analysis, metadata filters, vector search, full-text search, fusion, and traces.
- `answering`: evidence-pack construction, structured generation, citation validation, conflicts, and abstention.
- `timelines`: topic matching, relationship expansion, chronological ordering, and timeline DTOs.
- `evaluation`: benchmark fixtures, runs, metrics, per-question diagnostics, and strategy comparison.
- `providers`: generation and embedding interfaces plus Ollama adapters and deterministic test fakes.

Domain modules may depend on shared database and provider interfaces, but they do not call Ollama or issue cross-module queries through UI-specific code. API routes are thin adapters over application services.

### 4.3 Provider contracts

`EmbeddingProvider` accepts normalized texts and returns vectors plus embedding profile metadata. `GenerationProvider` accepts a prompt and response schema and returns validated structured output. The stored embedding profile includes provider, model, and vector dimension; changing it requires a full passage re-embedding operation.

The initial adapters use Ollama. Hosted providers can later implement the same contracts without changing ingestion, retrieval, answering, or evaluation services.

## 5. Data Model

### Workspace

Stores the single workspace name, creation time, and active embedding profile.

### Document

Stores filename, media type, title, document date, participants, source type, project, SHA-256 checksum, file path, ingestion status, active version, timestamps, and structured error details.

### Passage

Stores document ID, stable sequence number, normalized content, character offsets within the normalized document, a content hash, format-specific locator, PostgreSQL search vector, embedding, and timestamps.

The locator is typed data:

- Markdown/text: line range
- PDF: page number and offsets within extracted page text
- DOCX: paragraph range and offsets within normalized paragraph text

### Decision

Stores statement, effective date, owner, status (`active`, `proposed`, `rejected`, or `superseded`), reasons, alternatives, project, feature/topic, extraction confidence, provenance (`extracted` or `user_corrected`), `user_edited`, review state, and timestamps.

### DecisionEvidence

Associates a decision with one or more passages and exact offsets inside each passage. It identifies the primary evidence passage and preserves the evidence content hash used when the association was created.

### DecisionRelation

Links two decisions using `supersedes`, `revises`, or `relates_to`. It stores whether the link was model-inferred or user-confirmed, a confidence category for inferred links, and timestamps.

### DecisionRevision

Records field-level before and after values for manual corrections. This provides a small audit trail without adding user identity or collaboration concepts.

### IngestionJob

Stores document ID, stage, status (`pending`, `running`, `completed`, or `failed`), progress, attempt count, request ID, structured error, and timestamps.

### RetrievalTrace

Stores request ID, normalized question, extracted filters, candidates and scores from each retrieval strategy, fused ranks, selected evidence, timing by stage, and configuration snapshot. Source text can be referenced by passage ID rather than duplicated.

### Evaluation records

- `EvaluationQuestion`: question, expected answer summary, expected documents/passages, expected status, answer-or-abstain expectation, and tags.
- `EvaluationRun`: strategy, configuration snapshot, dataset version, model profile, start/end times, and aggregate metrics.
- `EvaluationResult`: retrieved ranks, generated output, citation checks, expected-versus-actual values, latency, and failure reason.

## 6. Document Ingestion

### 6.1 Supported formats

- `.md`: preserve heading and line context.
- `.txt`: normalize plain text and preserve line ranges.
- `.pdf`: extract embedded text page by page and preserve page anchors.
- `.docx`: extract paragraphs and basic heading/table text while preserving paragraph anchors.

The MVP does not attempt layout reconstruction. PDF tables and multi-column layouts may extract imperfectly and are documented limitations. Empty extracted text from a PDF is treated as likely scanned content and rejected as requiring OCR.

### 6.2 Pipeline

1. Validate extension, media type, configurable size limit, and readable content.
2. Calculate a SHA-256 checksum.
3. Skip indexing when the active document checksum is unchanged.
4. Extract format-specific text and locator metadata.
5. Normalize whitespace without losing locator mappings.
6. Extract document title, date, participants, source type, and project metadata using deterministic signals followed by structured model extraction where needed.
7. Create passage-sized chunks using headings/paragraph boundaries with bounded overlap.
8. Generate embeddings in batches.
9. Extract decisions through schema-constrained generation.
10. Validate statuses, dates, evidence spans, and referenced passages.
11. Infer candidate decision relationships and flag uncertain ones for review.
12. Commit the new active document version transactionally and mark the job completed.

### 6.3 Idempotency and document changes

The checksum makes repeated uploads idempotent. A modified document is processed into a staged version; its passages and automatically extracted decisions become active only after the complete pipeline succeeds. A failed re-index leaves the previous active version searchable.

Automatically extracted records from the replaced version may be retired. User-corrected decisions are retained and marked `needs_review` when their cited content hash no longer matches the new source. They are never silently overwritten.

Because FastAPI background tasks are not durable, an API restart marks stale `running` jobs as failed/interrupted. The UI exposes a retry action. The API runs as one worker in the MVP to avoid duplicated in-process jobs.

## 7. Decision Extraction

The generation provider receives one document section at a time plus a strict response schema. Each extracted decision includes its statement, date, owner, status, reasons, alternatives, topic, evidence quote, and candidate relationship to earlier decisions.

Validation rejects records when their evidence quote cannot be aligned to an exact passage. Missing optional fields remain null or empty; the system does not infer an owner or date without evidence. Document date may be used as a clearly identified fallback for timeline ordering, not represented as a known decision date.

Users inspect and correct records from the Decision Detail screen. They can edit structured fields and relationships, but the source passage remains immutable. Corrections create `DecisionRevision` records and set `user_edited`.

## 8. Hybrid Retrieval

### 8.1 Query analysis

The question service identifies requested facets such as what, why, who, when, change history, and related topic. It extracts only explicit metadata filters for date, person, project, and document type. Ambiguous phrases remain search text rather than becoming restrictive filters.

### 8.2 Candidate retrieval

- Vector search returns the top 20 passages using cosine similarity.
- PostgreSQL full-text search returns the top 20 passages using document-language text search and ranking.
- Structured decision fields are searched and their evidence passages added as candidates.
- Explicit metadata filters are applied before ranking.

### 8.3 Fusion

Reciprocal Rank Fusion combines the ranked lists using a documented, configurable constant. Duplicate passages are merged by passage ID. Related decisions and limited neighboring passage context are added after fusion, then an evidence pack is created within the generation context budget.

An optional `Reranker` interface is defined but no additional reranking model is required for the MVP. The evaluation dashboard compares semantic-only retrieval with hybrid retrieval using identical questions and filters.

### 8.4 Retrieval trace

The developer panel displays query interpretation, applied filters, candidates from each strategy, raw ranks/scores, fused rank, selected evidence, configuration, and latency. This is a first-class learning and debugging feature.

## 9. Evidence-Backed Answering

The generation model receives only the question, selected evidence pack, and response contract. It returns:

- A concise answer
- Atomic factual claims
- Passage IDs supporting each claim
- Conflicting evidence
- Unsupported question facets
- A confidence category based on evidence coverage, not a fabricated numeric probability

A deterministic structural verifier confirms that every citation resolves, quoted text exactly matches stored content, offsets are valid, passage hashes match, and central claims include at least one citation. Lightweight field checks confirm that cited passages contain expected explicit entities or dates when those are claimed. Semantic entailment is not treated as perfectly deterministic; evaluation fixtures measure faithfulness and expose failures.

For a multi-part question, the response may answer supported facets and explicitly abstain from unsupported facets. It fully abstains when no central claim has sufficient evidence. Evidence thresholds are calibrated against the versioned evaluation set and saved with the run configuration.

When active evidence conflicts on owner, date, reason, or status, the answer presents the competing evidence and avoids selecting a winner unless an explicit supersession relationship resolves it.

## 10. Decision Timelines

Timeline construction is deterministic over stored decisions and relations:

1. Match decisions to the selected topic using normalized topic fields plus hybrid retrieval.
2. Expand explicit `supersedes`, `revises`, and `relates_to` links.
3. Order by known decision date, using documented fallback ordering when absent.
4. Label each event with status and relationship to earlier events.
5. Attach exact evidence to every event.

Model-inferred, unconfirmed relationships appear as `possible revision`; they do not automatically change another decision's status. A user-confirmed `supersedes` link causes the earlier decision to display as superseded while preserving its historical status and evidence.

## 11. API Surface

- `POST /documents`: upload one or more supported documents.
- `GET /documents`: list documents and ingestion states.
- `GET /documents/{id}`: return metadata, source content, passages, and error details.
- `POST /documents/{id}/reindex`: retry or reprocess a document.
- `GET /decisions`: filter/search decisions.
- `GET /decisions/{id}`: return the structured record, revisions, relations, and evidence.
- `PATCH /decisions/{id}`: correct fields or review state.
- `POST /decisions/{id}/relations`: create or confirm a relation.
- `POST /questions`: retrieve evidence, generate, verify, and return the answer plus trace ID.
- `GET /retrieval-traces/{id}`: return the developer trace.
- `GET /timelines?topic=...`: return a cited ordered timeline.
- `POST /evaluations/runs`: start a benchmark run for a named strategy.
- `GET /evaluations/runs/{id}`: return status, aggregate metrics, and per-question results.

All errors use a consistent response with a stable code, user-readable message, request ID, retryability, and optional field details.

## 12. User Interface

### Workspace

Shows uploaded documents, extracted metadata, ingestion stage/progress, modification state, decision count, retry controls, and actionable errors. Upload accepts only the supported formats.

### Ask

Shows the question, concise answer, explicit partial/full abstention, conflict warnings, numbered citations, exact supporting passages, document links, and a collapsible developer trace.

### Decision Timeline

Shows decisions chronologically for a selected topic using status and relationship labels. Every event links to its decision and evidence.

### Decision Detail

Shows structured fields, evidence, extraction provenance, review state, relationship editor, confidence category, and correction history. Users can correct structured values without editing source text.

### Evaluation Dashboard

Shows semantic-only versus hybrid aggregate metrics, run configuration, latency, and a per-question table with retrieved ranks, citations, abstention behavior, and failure reasons.

The frontend polls ingestion and evaluation job endpoints. WebSockets are intentionally excluded.

## 13. Errors, Reliability, and Observability

- Upload validation occurs before a job is created.
- Each background stage is persisted with status and timestamps.
- Provider calls use bounded timeouts and limited exponential retries for transient failures.
- Schema-invalid model output is retried once with a validation repair prompt, then recorded as `model_output_invalid`.
- One document failure does not block other documents.
- Database activation of a new document version is transactional.
- Provider unavailability results in an explicit retryable error; it never falls back to unsupported answers.
- Request IDs connect API errors, jobs, retrieval traces, answer traces, and evaluation results.
- Logs are structured and local. No external telemetry service is required.

## 14. Evaluation and Testing

### Evaluation dataset

Approximately 20 versioned questions include expected answer summaries, expected source documents or passages, expected decision status, expected answer/abstain behavior, and topical tags. The dataset includes multi-part questions, supersession, conflicts, and unsupported questions.

### Metrics

- Top-five retrieval hit rate
- Mean Reciprocal Rank
- Citation correctness
- Answer faithfulness
- Abstention accuracy
- End-to-end and stage latency

Hybrid and semantic-only strategies run against the same dataset, embedding profile, and generation profile. Each aggregate result links to per-question traces. The README contains measured results, not placeholder values.

### Automated tests

- Unit: metadata parsing, chunking, locator mapping, RRF, evidence alignment, citation validation, abstention rules, and timeline ordering.
- Integration: PostgreSQL full-text/vector queries, staged ingestion transactions, re-index preservation, and API endpoints.
- Provider contract: Ollama adapters plus deterministic fake generation and embedding providers.
- Frontend component: upload/status states, answer citations, conflicts, errors, polling, corrections, and timeline rendering.
- Smoke: Docker Compose upload → index → ask → cited answer → timeline.

Tests do not require live model output except for explicitly marked local-provider smoke tests. Deterministic fakes keep the main suite repeatable.

## 15. Security and Local-First Boundaries

- Filenames are sanitized and uploads receive generated storage names.
- File type, media type, and size are validated.
- Parsers run without executing macros, embedded scripts, links, or document instructions.
- Extracted document text is untrusted evidence, never system instructions.
- Model prompts clearly delimit evidence and prohibit following instructions found inside documents.
- The API binds locally by default; there is no authentication and it must not be exposed publicly.
- No source content or telemetry leaves the machine when local Ollama providers are selected.

## 16. Delivery Allocation

- Foundation, Docker Compose, schema, and sample data: 6 hours
- Multi-format ingestion and decision extraction: 11 hours
- Hybrid retrieval and trace capture: 9 hours
- Evidence-backed answers, validation, conflicts, and abstention: 8 hours
- Timeline and manual correction workflow: 6 hours
- Evaluation suite and dashboard: 6 hours
- Tests, README, demo script, and final polish: 4 hours

If time runs short, preserve ingestion correctness, hybrid retrieval, citations, abstention, one supersession timeline, and evaluation. Reduce visual polish and secondary filtering before reducing evidence guarantees.

## 17. Key Trade-offs and Limitations

- A modular monolith makes boundaries visible without consuming the week on distributed operations.
- FastAPI background tasks are sufficient for a single-worker demo but are not durable job infrastructure.
- RRF is transparent and deterministic; an additional reranking model is deferred until evaluation proves it necessary.
- Local models protect data and demonstrate provider abstraction but may be slower and less capable than hosted models.
- Exact source anchors are reliable for normalized extracted text, not pixel-perfect PDF coordinates.
- PDF layout, tables, and multi-column text may degrade extraction quality.
- Relationship inference is assistive; only explicit or user-confirmed links drive authoritative supersession behavior.
- The evaluation set is intentionally small and project-specific, so results demonstrate disciplined measurement rather than broad production generalization.

## 18. Implementation Planning Constraints

The implementation plan must maintain module boundaries, introduce provider fakes before model-dependent orchestration, and build one end-to-end vertical slice early. It must avoid microservices, external integrations, OCR, queues, and unmeasured framework abstractions. Each milestone must leave the repository runnable and testable.
