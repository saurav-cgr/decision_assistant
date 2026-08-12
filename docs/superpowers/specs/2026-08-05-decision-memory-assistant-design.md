# Decision Memory Assistant — MVP Design

**Date:** 2026-08-05  
**Status:** Approved; inference-provider amendment approved 2026-08-11
**Delivery budget:** Approximately 50 focused hours  
**Primary objective:** Produce a portfolio-quality AI engineering project that demonstrates architectural judgment, evidence-grounded generation, retrieval evaluation, and privacy-aware provider abstraction.

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
- Run application services and persistent data locally through Docker Compose while using Gemini behind generation and embedding provider interfaces.

### Definition of done

- A clean Docker Compose installation starts the frontend, API, and PostgreSQL with pgvector; a user-supplied Gemini API key enables model calls.
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

Docker Compose runs three required local components:

1. **Web:** React and TypeScript single-page application.
2. **API:** Python and FastAPI modular monolith, running as one worker for the MVP.
3. **Database:** PostgreSQL with the pgvector extension.

Gemini is an external managed dependency used for generation and embeddings. Uploaded source files, extracted text, embeddings, and database data use local Docker volumes as the application's primary persistence. Google also processes transmitted request content according to its applicable terms; the design does not claim that transmitted copies remain only on the local machine. The browser communicates only with FastAPI. FastAPI owns ingestion orchestration, domain rules, retrieval, answer construction, evaluation, provider calls, and secret isolation.

#### 4.1.1 Gemini transmission inventory

- **Metadata extraction:** when deterministic parsing leaves fields missing, an explicit bounded beginning-of-document sample and names of the missing fields are sent for structured completion.
- **Decision extraction:** normalized passage batches, passage IDs, and extraction instructions are sent. This can cover the complete document across multiple requests.
- **Document embeddings:** every normalized passage is sent with document-retrieval formatting.
- **Question retrieval:** the user's question is sent with query-retrieval formatting to obtain its vector.
- **Answer generation:** the question, selected evidence passages, passage IDs, supported corrected fields, and response schema are sent.
- **Evaluation:** benchmark questions, selected evidence, generated claims, expected/judge prompt material, and configuration identifiers needed by the generation/judge call are sent.
- **Not sent intentionally:** original binary files, local storage paths, database credentials, the Gemini API key in request content, unrelated passages during answering, or application telemetry.

Provider request/response metadata may still be processed or retained by Google under its terms. This MVP is approved only for the fictional Atlas corpus and other non-confidential demo content.

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
- `providers`: generation and embedding interfaces, centralized provider construction, Gemini adapters, optional Ollama adapters, and deterministic test fakes.

Domain modules may depend on shared database and provider interfaces, but they do not import a concrete model adapter or issue cross-module queries through UI-specific code. API routes are thin adapters over application services. A composition-root factory selects providers from validated settings so ingestion, retrieval, answering, and evaluation use one consistent provider configuration.

### 4.3 Provider contracts

`EmbeddingProvider` accepts an ordered, non-empty list of normalized texts plus an explicit purpose (`document` or `query`) and returns the same number of vectors in input order. For `gemini-embedding-2`, Google's Developer API does not support `EmbedContentConfig.task_type`; the adapter must omit that field. The supported mapping is therefore versioned prompt formatting: document input becomes `title: none | text: {content}` and query input becomes `task: search result | query: {content}` under `retrieval-prefix-v1`. Mocked request tests assert both the formatted `contents` and absence of `task_type`. The adapter sends at most 32 passage inputs per request; normal ingestion chunks are at most 1,500 characters, safely below the model's 8,192-token per-input limit. It never silently truncates. Every returned vector must contain exactly 768 finite, non-boolean numeric values.

`GenerationProvider` accepts a prompt and Pydantic response model and exposes a generation profile. The pinned MVP profile is provider `gemini`, model `gemini-3.1-flash-lite`, Google Gen AI SDK `2.13.0`, Gemini Developer API `v1beta`, temperature `0`, JSON-schema response mode, and prompt-contract version `gemini-json-v1`. This stable model supports structured output and temperature-zero requests on the free tier and replaces the former `gemini-2.5-flash-lite` default, which the Gemini API rejects for new users. The adapter sends the response model's JSON schema and then performs local Pydantic validation; if the service rejects a supported schema, the call fails rather than falling back to unconstrained text. Provider prompts are bounded by a configured 100,000-character budget and are never silently truncated. Metadata extraction uses an explicit bounded beginning-of-document sample when deterministic fields are missing; decision extraction partitions passages into ordered batches within the prompt budget.

Configuration snapshots store the full embedding profile `(provider, model, dimension, adapter_config_version)` and generation profile `(provider, model, API version, SDK version, temperature, schema mode, prompt_contract_version)`. Gemini is the default provider for both contracts. Embeddings use `gemini-embedding-2` with 768 output dimensions, preserving the existing fixed `vector(768)` column while changing the embedding space. The MVP rejects any configured adapter dimension other than 768 as `provider_configuration_invalid`.

Stable provider error codes are `provider_configuration_invalid`, `provider_authentication_failed`, `provider_rate_limited`, `provider_quota_exhausted`, `provider_unavailable`, `provider_input_too_large`, `provider_schema_unsupported`, and `provider_response_invalid`. A short rate limit with a usable `Retry-After`, timeout, or transient 5xx is retryable within the bounded request budget. Invalid configuration/credentials, exhausted daily quota, oversize input, unsupported schema, and invalid output are non-retryable for the current operation. Provider messages are sanitized before persistence or logging.

The optional Ollama adapter remains a demonstration of substitutability, but Ollama is not required for the default Compose startup, smoke test, or recorded demo.

## 5. Data Model

### Workspace

Stores the single workspace name, creation time, and corpus-active embedding profile. The configured profile comes from runtime settings. When there are no active passages, `migration_pending` is false regardless of the stored corpus profile; the first successful ingestion sets the corpus-active profile to the configured profile. For a non-empty corpus, `migration_pending` is derived when the configured profile differs from the corpus-active profile or any active passage lacks the configured profile.

### Document

Represents the stable logical document. It stores the workspace ID, display filename, media type, active version ID, and timestamps. Only the active version participates in normal retrieval.

### DocumentVersion

Owns one immutable uploaded revision of a document. It stores the document ID, monotonically increasing version number, title, document date, participants, source type, project, SHA-256 checksum, stored file path, lifecycle state (`staging`, `active`, `retired`, or `failed`), timestamps, and structured error details. `Document.active_version_id` is updated in the same transaction that activates a completed version; at most one version per document is active.

### Passage

Belongs to a `DocumentVersion`. It stores a stable sequence number within that version, normalized content, character offsets within the normalized document, a content hash, format-specific locator, PostgreSQL search vector, embedding, embedding profile, and timestamps. Passage IDs never span versions. The embedding and embedding profile are derived, replaceable data; changing them does not change source identity, locators, decisions, evidence, or correction history.

The locator is typed data:

- Markdown/text: line range
- PDF: page number and offsets within extracted page text
- DOCX: paragraph range and offsets within normalized paragraph text

### Decision

Belongs to the `DocumentVersion` from which it originated. It stores statement, effective date, owner, status (`active`, `proposed`, `rejected`, or `superseded`), reasons, alternatives, project, feature/topic, extraction confidence, provenance (`extracted` or `user_corrected`), aggregate review state, `user_edited`, retirement state, and timestamps.

### DecisionEvidence

Associates a whole decision or a named decision field with one or more passages and exact offsets inside each passage. It stores the field name when applicable, evidence-support state (`supported`, `unsupported`, or `needs_review`), identifies the primary evidence passage, and preserves the evidence content hash used when the association was created. The latest field-level associations determine which corrected values may enter an evidence pack.

### DecisionRelation

Links two decisions using `supersedes`, `revises`, or `relates_to`. It stores whether the link was model-inferred or user-confirmed, a confidence category for inferred links, and timestamps.

### DecisionRevision

Records field-level before and after values for manual corrections, the evidence passages selected for the correction, and the resulting evidence-support state. This provides a small audit trail without adding user identity or collaboration concepts.

### IngestionJob

Stores document ID, stage, status (`pending`, `running`, `completed`, or `failed`), progress, attempt count, request ID, structured error, and timestamps.

### RetrievalTrace

Stores request ID, normalized question, extracted filters, candidates and scores from each retrieval strategy, fused ranks, selected evidence, timing by stage, and configuration snapshot. Source text can be referenced by passage ID rather than duplicated.

### Evaluation records

- `EvaluationQuestion`: question, expected answer summary, expected documents/passages, expected status, answer-or-abstain expectation, and tags.
- `EvaluationRun`: strategy, status (`pending`, `running`, `completed`, or `failed`), completed/total question counts, structured failure, configuration snapshot, dataset version, model and judge profiles, start/end times, and aggregate metrics.
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
8. Generate document-purpose Gemini embeddings in bounded batches; validate cardinality, order, profile, dimension, and finite values before creating passages.
9. Extract decisions through schema-constrained generation.
10. Validate statuses, dates, evidence spans, and referenced passages.
11. Infer candidate decision relationships and flag uncertain ones for review.
12. Commit the new active document version transactionally, set the workspace corpus-active profile when all active passages share it, and mark the job completed.

### 6.3 Idempotency and document changes

The checksum makes repeated source uploads idempotent. An identical checksum is skipped because embedding migration is a separate derived-data operation. A modified document creates a `staging` `DocumentVersion`; all new passages, decisions, evidence, and relationships reference that version. After every stage succeeds, one transaction retires the prior version, activates the staged version, and updates `Document.active_version_id`. A failed source re-index marks only the staged version failed and leaves the prior version searchable when its embedding profile matches the corpus-active profile.

Automatically extracted decisions belonging to the replaced version are retired with it. User-corrected decisions remain visible in history but become `needs_review` and are excluded from answers and authoritative timelines until their evidence is re-associated with active-version passages. They are never silently overwritten. Retired versions are retained for the MVP so revision history and old citations remain inspectable; automatic retention cleanup is out of scope.

Because FastAPI background tasks are not durable, an API restart marks stale `running` jobs as failed/interrupted. The UI exposes a retry action. The API runs as one worker in the MVP to avoid duplicated in-process jobs.

### 6.4 Embedding-profile migration

Embedding migration never creates a `DocumentVersion` and never re-runs parsing, metadata extraction, decision extraction, evidence alignment, or relationship inference. Therefore user corrections, evidence associations, passage IDs, offsets, hashes, revisions, and authoritative timeline state remain unchanged.

Three states are explicit:

- **Configured profile:** requested by environment settings for new calls.
- **Corpus-active profile:** stored on `Workspace.embedding_profile` and shared by every searchable active passage.
- **Migration pending:** configured and corpus-active profiles differ, or an active passage has a missing/different profile.

On startup, the API succeeds even when migration is pending, but semantic/hybrid retrieval and evaluation return `embedding_reindex_required`. Keyword-only inspection, source viewing, and correction workflows remain available. Every vector query both joins through the active `DocumentVersion` and filters `Passage.embedding_profile` to the configured profile; the pre-query gate rejects the operation if any active passage is mismatched, so partial-corpus vector search is impossible.

The MVP exposes a containerized embedding-migration command. It acquires a workspace-scoped advisory guard before reading the active-passage snapshot and holds it through all provider calls and final cutover; ingestion obtains the same guard before source activation, so active membership cannot change during migration. The command obtains and validates Gemini embeddings in bounded batches and stages them in process memory for this small single-workspace corpus. Only after every batch succeeds does one database transaction verify the snapshotted passage/version identities, update active passage vectors/profiles, and flip `Workspace.embedding_profile`. Snapshot drift aborts without writes. Any failure discards staged results and leaves the old corpus-active vectors/profile intact. Tests prove that decision records and user corrections are byte-for-byte unchanged across migration.

## 7. Decision Extraction

The generation provider receives one ordered, prompt-budgeted passage batch at a time plus a strict response schema. Batch results are merged deterministically before evidence alignment. Each extracted decision includes its statement, date, owner, status, reasons, alternatives, topic, evidence quote, and candidate relationship to earlier decisions.

Validation rejects records when their evidence quote cannot be aligned to an exact passage. Missing optional fields remain null or empty; the system does not infer an owner or date without evidence. Document date may be used as a clearly identified fallback for timeline ordering, not represented as a known decision date.

Users inspect and correct records from the Decision Detail screen. They can edit structured fields and relationships, but the source passage remains immutable. A correction may retain existing evidence or select one or more active-version passages. The server validates citation existence, offsets, and hashes, then creates a `DecisionRevision` and sets `user_edited`.

A user may deliberately save a correction without supporting evidence, but it is labeled `unsupported`. Unsupported and `needs_review` fields remain visible as human notes but are excluded from evidence-backed answers and authoritative timeline transitions. Supported corrections may be used in answers with their selected passages; the UI identifies them as user-corrected interpretations rather than source text.

## 8. Hybrid Retrieval

### 8.1 Query analysis

The question service identifies requested facets such as what, why, who, when, change history, and related topic. It extracts only explicit metadata filters for date, person, project, and document type. Ambiguous phrases remain search text rather than becoming restrictive filters.

### 8.2 Candidate retrieval

- Vector search embeds the question with query purpose and returns the top 20 passages using cosine similarity.
- PostgreSQL full-text search returns the top 20 passages using the configured English text-search dictionary and ranking. Per-document language detection is out of scope.
- Structured decision fields are searched and their evidence passages added as candidates.
- Explicit metadata filters are applied before ranking.

### 8.3 Fusion

Reciprocal Rank Fusion combines the ranked lists using a documented, configurable constant. Duplicate passages are merged by passage ID. Related decisions and limited neighboring passage context are added after fusion, then an evidence pack is created within the generation context budget.

No reranking model or interface is implemented in the MVP. The evaluation dashboard compares semantic-only retrieval with hybrid retrieval using identical questions and filters; reranking is considered only after measured results justify it.

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

A deterministic structural verifier confirms that every citation resolves to an active-version passage, quoted text exactly matches stored content, offsets are valid, passage hashes match, and central claims include at least one citation. Lightweight field checks confirm that cited passages contain expected explicit entities or dates when those are claimed. Unsupported and `needs_review` corrected fields cannot enter the evidence pack. Semantic entailment is not treated as perfectly deterministic; evaluation fixtures measure faithfulness and expose failures.

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

- `POST /api/v1/documents/upload`: upload one or more supported documents.
- `GET /api/v1/documents`: list documents and ingestion states.
- `GET /api/v1/documents/{id}`: return metadata, source content, passages, and error details.
- `POST /api/v1/documents/{id}/retry`: retry a failed document ingestion.
- `GET /api/v1/decisions`: filter/search decisions.
- `GET /api/v1/decisions/{id}`: return the structured record, revisions, relations, and evidence.
- `PATCH /api/v1/decisions/{id}`: correct fields or review state.
- `POST /api/v1/decisions/{id}/relations`: create or confirm a relation.
- `POST /api/v1/questions`: retrieve evidence, generate, verify, and return the answer plus trace ID.
- `GET /api/v1/retrieval-traces/{id}`: return the developer trace.
- `GET /api/v1/timelines?topic=...`: return a cited ordered timeline.
- `POST /api/v1/evaluations/runs`: start a benchmark run for a named strategy.
- `GET /api/v1/evaluations/runs/{id}`: return status, aggregate metrics, and per-question results.

All public business endpoints use major-version URL prefix `/api/v1`. Infrastructure endpoints `/health`, `/ready`, `/docs`, and `/openapi.json` remain unversioned. No unversioned compatibility aliases are exposed because no external client predates this contract. Compatible additions remain in v1; a future breaking request or response contract requires `/api/v2`.

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
- Provider calls use bounded timeouts and limited exponential retries with jitter for timeouts, rate limits, and transient server failures.
- API startup does not require a Gemini key. Unversioned `GET /health` is process/database liveness and remains successful in provider-degraded or migration-pending states. Unversioned `GET /ready` reports HTTP 200 only when the database is available, the selected providers have the required configuration (a key for Gemini), and no embedding migration is pending; otherwise it returns a sanitized HTTP 503 status without making a provider call. It checks configuration presence, not remote credential validity. Compose uses `/health` so the setup UI remains reachable; live smoke preflight uses `/ready`.
- A provider-dependent endpoint or ingestion job requested without a key fails with non-retryable `provider_configuration_invalid`; rejected credentials use `provider_authentication_failed`. The job/error remains inspectable and retryable only after configuration changes. API keys and raw provider response bodies are never logged.
- Bounded per-minute throttling uses `provider_rate_limited` and may retry when `Retry-After` fits the request budget. Exhausted daily/project quota uses non-retryable-for-this-operation `provider_quota_exhausted`; the UI advises waiting for reset or changing provider/tier.
- Schema-invalid model output is retried once with a validation repair prompt, then recorded as `model_output_invalid`.
- One document failure does not block other documents.
- Database activation of a new document version is transactional.
- Provider unavailability results in an explicit retryable error; it never falls back to unsupported answers.
- Request IDs connect API errors, jobs, retrieval traces, answer traces, and evaluation results.
- Logs are structured and local. No external telemetry service is required.
- CI uses deterministic fake providers and mocked-transport Gemini contract tests. A separately marked live-provider acceptance path requires an explicit Gemini API key; quota failure is reported as skipped/inconclusive, never as a pass.

## 14. Evaluation and Testing

### Evaluation dataset

Approximately 20 versioned questions include expected answer summaries, expected source documents or passages, expected decision status, expected answer/abstain behavior, and topical tags. The dataset includes multi-part questions, supersession, conflicts, and unsupported questions.

### Metrics

- **Top-five retrieval hit rate:** fraction of answerable questions for which at least one expected passage, or expected document when passage-level gold is unavailable, appears in the top five.
- **Mean Reciprocal Rank:** mean reciprocal position of the first expected relevant result, with zero for a miss.
- **Citation correctness:** fraction of answer citations that pass structural validation and point to a gold-relevant passage/document. Structural validity is also reported separately.
- **Answer faithfulness:** fraction of generated atomic claims judged supported by their cited passages using a versioned evaluation prompt, fixed judge profile, temperature-zero settings, and stored judge output. The final README result includes a manual audit of judge disagreements across the small dataset.
- **Abstention accuracy:** classification accuracy against the expected answer-versus-abstain label; partial abstentions are scored per expected question facet.
- **Latency:** median and p95 end-to-end time plus retrieval, generation, and verification stage timings.

Hybrid and semantic-only strategies run against the same dataset, embedding profile, and generation profile. Each aggregate result links to per-question traces. The README contains measured results, not placeholder values.

### Automated tests

- Unit: metadata parsing, chunking, locator mapping, RRF, evidence alignment, citation validation, abstention rules, and timeline ordering.
- Integration: PostgreSQL full-text/vector queries, staged ingestion transactions, re-index preservation, and API endpoints.
- Provider contract: mocked-transport Gemini request mapping, purpose formatting, schema handling, cardinality/order/profile/dimension/finite-value validation, retry/error classification, and secret redaction; optional Ollama contracts; deterministic fake generation and embedding providers.
- Frontend component: upload/status states, answer citations, conflicts, errors, polling, corrections, and timeline rendering.
- Smoke: a fake-provider Docker Compose upload → index → ask → cited answer → timeline path runs deterministically; a separate live Gemini acceptance repeats the full cited-answer flow.

Tests do not require live model output except for the explicitly marked Gemini acceptance. Mocked-transport tests validate the real adapter contract without network access. The live acceptance passes only after a real upload → Gemini embedding/extraction → question → cited answer → timeline flow. Missing credentials or quota exhaustion marks that check skipped/inconclusive and cannot satisfy the definition of done.

## 15. Security and Data Boundaries

- Filenames are sanitized and uploads receive generated storage names.
- File type, media type, and size are validated.
- Parsers run without executing macros, embedded scripts, links, or document instructions.
- Extracted document text is untrusted evidence, never system instructions.
- Model prompts clearly delimit evidence and prohibit following instructions found inside documents.
- The API binds locally by default; there is no authentication and it must not be exposed publicly.
- The Gemini API key is supplied through an uncommitted environment file, passed only to the API container, redacted from logs/errors, and never returned to the browser.
- Gemini embedding sends every normalized document chunk and query text to Google. Metadata/decision extraction can send the complete normalized document across requests. Answering and evaluation send questions, selected evidence, and judge material as listed in §4.1.1. Users must not ingest confidential material unless they accept Google's applicable data terms.
- The free tier is appropriate for the fictional Atlas portfolio corpus, not a privacy guarantee or production availability commitment. Quotas and terms may change.
- Source files, PostgreSQL data, and generated embeddings remain locally persisted; the application is therefore local-data-first, not fully offline or fully local-inference.

## 16. Delivery Allocation

- Foundation, Docker Compose, schema, and sample data: 6 hours
- Multi-format ingestion and decision extraction: 11 hours
- Hybrid retrieval and trace capture: 9 hours
- Evidence-backed answers, validation, conflicts, and abstention: 8 hours
- Timeline and manual correction workflow: 6 hours
- Evaluation suite and dashboard: 6 hours
- Tests, README, demo script, and final polish: 4 hours

If time runs short, preserve ingestion correctness, hybrid retrieval, citations, abstention, one supersession timeline, and evaluation. Reduce visual polish and secondary filtering before reducing evidence guarantees.

### 16.1 Scope priorities

**P0 — required for the 50-hour definition of done:**

- One workspace and one fixed English retrieval configuration
- Basic extraction for all four supported formats, with page/paragraph/line anchors and explicit parser errors
- One version-safe upload/re-index path
- Structured decision extraction and editing of the core fields
- Vector search, full-text search, RRF, and an inspectable text-based retrieval trace
- Evidence-backed answers with structural citation checks, conflicts, and partial/full abstention
- One reliable topic timeline with explicit supersession
- Approximately 20 evaluation fixtures, semantic-only versus hybrid comparison, required metrics, and per-question diagnostics
- The five functional screens, Docker Compose, core deterministic tests, one integration happy path, and one end-to-end smoke path

**P1 — include only if P0 is verified early:**

- Automatic cross-document relationship suggestions beyond relationships returned during extraction
- Rich correction-history visualization beyond a basic revision list
- Advanced filtering combinations and trace visual polish
- Broader parser handling for complex DOCX tables or difficult PDF layouts
- Additional component and integration edge-case coverage beyond the named reliability paths

If the project exceeds the time box, P1 is omitted and documented. P0 evidence guarantees, evaluation integrity, and runnable setup are not traded for cosmetic completeness.

## 17. Key Trade-offs and Limitations

- A modular monolith makes boundaries visible without consuming the week on distributed operations.
- FastAPI background tasks are sufficient for a single-worker demo but are not durable job infrastructure.
- RRF is transparent and deterministic; an additional reranking model is deferred until evaluation proves it necessary.
- Gemini removes the local model download and CPU bottleneck and improves demo reliability, but introduces network, quota, vendor, and data-governance dependencies.
- Retaining provider interfaces and the optional Ollama adapter demonstrates substitutability without making local inference part of the default runtime.
- Changing embedding provider, model, or retrieval-instruction version at 768 dimensions requires the atomic embedding migration; mixed embedding spaces are rejected. A different vector dimension is outside the MVP and requires an explicit pgvector/Alembic schema migration plus full re-index before an adapter can be enabled.
- Exact source anchors are reliable for normalized extracted text, not pixel-perfect PDF coordinates.
- PDF layout, tables, and multi-column text may degrade extraction quality.
- Relationship inference is assistive; only explicit or user-confirmed links drive authoritative supersession behavior.
- The evaluation set is intentionally small and project-specific, so results demonstrate disciplined measurement rather than broad production generalization.

## 18. Implementation Planning Constraints

The implementation plan must maintain module boundaries, keep deterministic provider fakes for model-independent orchestration, and preserve the existing end-to-end vertical slice. Gemini is the one approved external model integration; unrelated hosted connectors remain out of scope. The implementation must avoid microservices, OCR, queues, and unmeasured framework abstractions. Each milestone must leave the repository runnable and testable.
