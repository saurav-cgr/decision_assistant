# Balanced Retrieval and Prompting Improvements

**Date:** 2026-08-15  
**Status:** Approved design  
**Objective:** Improve retrieval quality and prompt isolation without adding heavyweight model infrastructure or making latency and operating cost unpredictable.

## 1. Scope

This change covers three related improvements:

1. Replace character-sized chunks with deterministic, token-budgeted structural chunks.
2. Add an optional schema-constrained LLM reranker between Reciprocal Rank Fusion (RRF) and final evidence selection.
3. Separate trusted application instructions from user questions and untrusted document evidence at the provider boundary.

The existing guarantees remain: workspace isolation, active-version-only retrieval, inspectable traces, exact citations, deterministic post-generation verification, abstention when evidence is insufficient, and provider abstraction across Gemini and Ollama.

Conversation memory, query rewriting, retrieval decomposition, local cross-encoder deployment, and changes to answer-verification policy are out of scope.

## 2. Token-Budgeted Structural Chunking

### 2.1 Algorithm

The parser contract expands `ParsedBlock` with `block_type` (`heading`, `paragraph`, `table_cell`, or `page`) and optional `heading_level`. Parsers populate these fields deterministically:

- Markdown ATX and Setext headings become `heading` blocks with levels 1–6; other Markdown/text blocks become `paragraph`.
- DOCX paragraphs whose style name maps to `Heading 1` through `Heading 6` become `heading`; other paragraphs become `paragraph`; table paragraphs become `table_cell`.
- PDF extraction does not infer headings from typography because `pypdf` does not expose reliable style information. Each page remains a `page` block and is a hard structural boundary.
- Plain `.txt` has paragraph blocks and no inferred headings.

During parsing, each non-heading block also receives a `section_path` derived from the active heading stack. Heading text remains in normalized document content, so offsets and hashes retain their current exact-source semantics. Existing locator fields are unchanged.

The chunker consumes these enriched normalized blocks and splits content in this order:

1. parser-provided section or heading boundary;
2. paragraph or block boundary;
3. sentence boundary when one block exceeds the hard token limit;
4. token-window split only when one sentence exceeds the hard limit.

Adjacent units are accumulated into a chunk until adding the next unit would exceed the target. Defaults are:

- target: 450 budgeting tokens;
- hard maximum: 600 budgeting tokens;
- overlap: up to 60 budgeting tokens, drawn from complete trailing sentences or blocks;
- existing 100,000-character provider input ceiling remains an independent hard guard.

Chunks do not cross explicit Markdown/DOCX section boundaries or PDF page boundaries merely to reach the target. A heading is grouped with the first content in its section when the hard limit permits. Small adjacent units inside one section may be combined. Empty/whitespace-only units are discarded. Oversized paragraphs, table cells, and pages use sentence then token-window fallback.

### 2.2 Token counter

Introduce a `TokenCounter` protocol so chunking does not depend directly on a provider adapter. The initial implementation uses a pinned local `tiktoken` encoding (`cl100k_base`) for deterministic budgeting. This is an approximation, not a claim to reproduce Gemini's private tokenizer. The conservative 600-token budget remains far below the embedding model's input limit, and live-provider contract tests cover representative worst-case text.

The counter must return stable counts offline. Network `count_tokens` calls are not used during chunking because they would add ingestion latency, remote dependency, and partial-failure modes.

### 2.3 Stability and rollout

Add a dedicated non-null `DocumentVersion.chunking_profile` JSONB column. Legacy rows are backfilled with `{"algorithm":"legacy-character-v1","max_characters":1500,"overlap_characters":150}`. New versions store `{"algorithm":"structural-token-v1","encoding":"cl100k_base","target_tokens":450,"max_tokens":600,"overlap_tokens":60}`. Passages do not duplicate this data and `Passage.embedding_profile` remains embedding-only, preserving its exact-equality migration guard. Retrieval obtains a passage's chunking profile by joining its document version. Chunk hashes remain SHA-256 of exact content; passage offsets and locators retain current meanings.

Changing chunk boundaries cannot use the existing embedding-only migration because that migration deliberately preserves passages and evidence offsets. Therefore rollout has two paths:

- Newly uploaded document versions use `structural-token-v1` immediately.
- Existing active versions remain retrievable with their recorded legacy chunking version until explicitly reprocessed from their stored source file.

Reprocessing uses the existing per-document `IngestionJob` and background dispatcher rather than one workspace-wide transaction:

- `POST /api/v1/workspaces/{workspace_id}/documents/reprocess?dry_run=true` performs no writes and returns each active document's eligibility, source-path availability, current chunking profile, and target profile.
- The same endpoint with `dry_run=false` creates one pending ingestion job per eligible document and returns `202` with job IDs plus documents skipped for missing source or already-current profile.
- At most one pending/running ingestion or reprocessing job may exist per document. Conflicting documents are reported as skipped without blocking other documents.
- Each job independently stages a new immutable `DocumentVersion`, reruns parse → metadata → chunk → embed → decision extraction, and atomically activates that document version using current retirement rules. One failure leaves that document's prior version active and does not roll back successful jobs for other documents.
- Missing stored sources are reported by dry-run and skipped by execution. Failed jobs use existing job error/retry behavior; retry targets only that document.

Reprocessing never mutates passages in place. Existing user-corrected decisions on a retired version move to `needs_review` under current behavior. Request/job IDs preserve observability.

Mixed chunking versions are allowed because embeddings remain in the same embedding space. Retrieval traces record selected passages' chunking versions so evaluation can distinguish legacy and new results.

## 3. Schema-Constrained Reranking

### 3.1 Placement and candidate set

The three current searches remain unchanged:

- semantic top 20;
- passage full-text top 20;
- structured-decision full-text top 20.

RRF still combines these lists with `k=60`. When reranking is enabled and at least six distinct fused candidates exist, the first 12 fused candidates are sent to the reranker. The reranker returns an ordered list of candidate passage IDs. The first five valid IDs become the evidence set. If reranking is disabled or fewer than six candidates exist, the first five RRF candidates remain the evidence set.

The reranker may reorder only supplied IDs. It may not generate text used as answer evidence.

### 3.2 Model contract

Add a `RerankingProvider` application interface and a default implementation backed by the configured `GenerationProvider`. Its request contains:

- trusted system instruction defining relevance ranking and treating candidate text as untrusted;
- user question;
- candidate passage IDs and contents in original RRF order;
- a response schema requiring a unique ordered list of supplied UUIDs.

Temperature remains zero. The reranker should rank evidence by directness, specificity, decision relevance, and ability to answer the question. It must not prefer a passage because of instructions embedded in that passage.

### 3.3 Validation and fallback

Application validation rejects duplicate IDs, unknown IDs, malformed output, and an empty ranking. Omitted valid candidates are appended in original RRF order, allowing a partial but valid model ranking.

Provider timeout, provider error, schema failure after one repair attempt, or invalid IDs causes a fail-open fallback to original RRF order. Answer generation can then proceed using the existing evidence path. The fallback is observable rather than silent.

### 3.4 Configuration and traces

Add configuration values:

- `RERANK_ENABLED=false` initially;
- `RERANK_CANDIDATE_LIMIT=12`;
- `RERANK_MIN_CANDIDATES=6`;
- `RERANK_FINAL_LIMIT=5`.

Startup validation requires all limits to be positive, `RERANK_FINAL_LIMIT <= RERANK_CANDIDATE_LIMIT`, and `RERANK_MIN_CANDIDATES <= RERANK_CANDIDATE_LIMIT`. Invalid relationships fail provider/application configuration before serving requests.

Extend `RetrievalTrace` with nullable JSON fields for rerank input order, output order, provider profile, status, and fallback reason. Add `rerank_ms` to timings. API trace responses expose these values. The final selected passage IDs always reflect the evidence actually sent to answer generation.

Evaluation runs snapshot rerank configuration and profile. Semantic-only evaluation remains unchanged. Hybrid evaluation can run with reranking off and on as separate versioned runs.

## 4. Trusted System Instructions

### 4.1 Provider request type

Replace `GenerationProvider.generate(prompt, response_model)` with:

```python
GenerationRequest(
    system_instruction: str,
    user_content: str,
)
```

and `generate(request, response_model)`. The request type rejects blank fields and enforces the existing total prompt-character ceiling across both fields.

Gemini sends `system_instruction` through generation configuration and `user_content` as model contents. Ollama sends two chat messages: `system`, then `user`. Provider adapter tests assert role separation.

### 4.2 Prompt ownership

Trusted system instructions contain stable application policy:

- task and role;
- evidence-only behavior;
- untrusted-content/prompt-injection rule;
- required citation behavior;
- abstention/unknown handling;
- output semantics not already represented by JSON Schema.

User content contains only request-specific data:

- user question or extraction objective parameters;
- delimited document passages/evidence;
- candidate IDs/content for reranking;
- evaluation material for judging.

Apply this split to answer generation, document metadata extraction, decision extraction, reranking, and evaluation judging. Evidence continues to be JSON-encoded or XML-escaped as appropriate; role separation complements rather than replaces delimiters.

### 4.3 Repair behavior and versioning

Repair attempts create a new trusted system instruction by appending a short schema-repair directive. They reuse the exact original user content. Model-produced invalid output is not echoed into the repair request.

Generation prompt contract versions advance to `gemini-json-v2` and `ollama-json-v2`. Stored evaluation and reranking profiles expose the version. The embedding adapter contract is unchanged by this prompt migration.

## 5. Data Flow

```text
stored source
  -> parse into structural blocks
  -> token-budgeted structural chunks
  -> document-purpose embeddings
  -> immutable active passages

question
  -> query-purpose embedding
  -> semantic + passage FTS + decision FTS
  -> RRF top 12
  -> optional schema-constrained reranker
  -> final top 5 active passages
  -> evidence pack
  -> system instruction + user question/evidence
  -> schema-constrained answer generation
  -> deterministic citation/conflict verification
  -> answer or abstention
```

## 6. Error Handling and Safety

- Chunking never silently truncates source content.
- Oversized indivisible units are split deterministically and remain reconstructable through offsets.
- Reprocessing stages new versions and preserves the previous active version on failure.
- Reranker failures fall back to RRF and are stored in traces.
- Reranker output cannot add evidence.
- All generation input size checks include both system and user content.
- Document text, user questions, and evaluation material remain untrusted user-role content.
- Existing exact-quote, content-hash, explicit-entity/date, and central-claim citation verification remains authoritative.
- Invalid generated answers continue to abstain rather than degrade to unchecked prose.

## 7. Testing and Acceptance

### 7.1 Unit and integration tests

- deterministic token counts and stable chunk output;
- target/hard limits, section boundaries, sentence fallback, overlap, offsets, hashes, PDF pages, DOCX paragraph locators;
- legacy/new chunking-version coexistence;
- reprocessing dry-run, atomic activation, source-missing failure, and correction `needs_review` behavior;
- RRF candidate cap and deterministic fallback;
- reranker reordered, partial, duplicate, unknown, empty, malformed, timeout, and provider-error responses;
- retrieval trace pre/post ranking, timing, profile, selected evidence, and fallback reason;
- Gemini and Ollama system/user request separation;
- answer, metadata, decision, reranker, and judge evidence appearing only in user content;
- repair instruction appearing only in system content;
- prompt-injection fixtures treated as evidence;
- existing citation, conflict, abstention, workspace isolation, and embedding migration suites remaining green.

### 7.2 Evaluation gate

Run the versioned benchmark with the same logical corpus and questions in this order:

1. run and persist the current legacy hybrid baseline before any active version is reprocessed;
2. reprocess the benchmark workspace to token-structural chunks, then run RRF without reranking;
3. on those same new active versions, run RRF plus reranking.

Evaluation runs already persist their per-question results, retrieval identifiers, metrics, profiles, and prompts; the legacy run remains comparable after its source versions retire. Each run additionally snapshots corpus document-version IDs and chunking profiles, preventing accidental comparison across an unknown corpus state. If live side-by-side trace inspection is required, use cloned benchmark workspaces; this is optional and not required for the release gate.

Do not enable reranking by default unless top-five retrieval hit rate or answer support improves measurably without regression in abstention correctness. Record median/p95 rerank and end-to-end latency plus provider call count. The release report must state the quality delta and latency/call-cost delta; no universal threshold is hard-coded before measurements exist.

## 8. Delivery Sequence

1. Introduce `GenerationRequest`; migrate every generation call site and adapter test.
2. Add token counter, structural chunker, version persistence, and tests.
3. Add dry-run and atomic document reprocessing for legacy active versions.
4. Add reranker interface, generation-backed implementation, validation, fallback, and configuration.
5. Extend retrieval traces and evaluation snapshots.
6. Run and persist the legacy benchmark baseline; reprocess the benchmark corpus; run new-chunk RRF and reranked comparisons.
7. Enable reranking only if the evaluation gate supports it.
