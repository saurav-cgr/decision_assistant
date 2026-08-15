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

The chunker will continue to consume normalized parser blocks and preserve exact source offsets and locators. It will split content in this order:

1. parser-provided section or heading boundary;
2. paragraph or block boundary;
3. sentence boundary when one block exceeds the hard token limit;
4. token-window split only when one sentence exceeds the hard limit.

Adjacent units are accumulated into a chunk until adding the next unit would exceed the target. Defaults are:

- target: 450 budgeting tokens;
- hard maximum: 600 budgeting tokens;
- overlap: up to 60 budgeting tokens, drawn from complete trailing sentences or blocks;
- existing 100,000-character provider input ceiling remains an independent hard guard.

Chunks do not cross section boundaries merely to reach the target. Small adjacent units inside one section may be combined. Empty/whitespace-only units are discarded.

### 2.2 Token counter

Introduce a `TokenCounter` protocol so chunking does not depend directly on a provider adapter. The initial implementation uses a pinned local `tiktoken` encoding (`cl100k_base`) for deterministic budgeting. This is an approximation, not a claim to reproduce Gemini's private tokenizer. The conservative 600-token budget remains far below the embedding model's input limit, and live-provider contract tests cover representative worst-case text.

The counter must return stable counts offline. Network `count_tokens` calls are not used during chunking because they would add ingestion latency, remote dependency, and partial-failure modes.

### 2.3 Stability and rollout

Add an application chunking contract version, `structural-token-v1`, stored on each `DocumentVersion` and copied into each passage's metadata/profile. Chunk hashes remain SHA-256 of exact content; passage offsets and locators retain current meanings.

Changing chunk boundaries cannot use the existing embedding-only migration because that migration deliberately preserves passages and evidence offsets. Therefore rollout has two paths:

- Newly uploaded document versions use `structural-token-v1` immediately.
- Existing active versions remain retrievable with their recorded legacy chunking version until explicitly reprocessed from their stored source file.

An explicit workspace reprocessing operation stages a new immutable `DocumentVersion`, reruns parse → metadata → chunk → embed → decision extraction, then atomically activates it using existing version-retirement rules. It never mutates passages in place. Existing user-corrected decisions on the retired version move to `needs_review` under current behavior. A dry-run reports affected documents and missing source files before writes.

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

Run the versioned benchmark with the same corpus and questions for:

1. current legacy hybrid baseline;
2. token-structural chunks with RRF;
3. token-structural chunks with RRF plus reranking.

Do not enable reranking by default unless top-five retrieval hit rate or answer support improves measurably without regression in abstention correctness. Record median/p95 rerank and end-to-end latency plus provider call count. The release report must state the quality delta and latency/call-cost delta; no universal threshold is hard-coded before measurements exist.

## 8. Delivery Sequence

1. Introduce `GenerationRequest`; migrate every generation call site and adapter test.
2. Add token counter, structural chunker, version persistence, and tests.
3. Add dry-run and atomic document reprocessing for legacy active versions.
4. Add reranker interface, generation-backed implementation, validation, fallback, and configuration.
5. Extend retrieval traces and evaluation snapshots.
6. Reprocess the benchmark corpus; run baseline/RRF/reranked comparisons.
7. Enable reranking only if the evaluation gate supports it.

