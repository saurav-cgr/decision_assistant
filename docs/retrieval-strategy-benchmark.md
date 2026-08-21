# Retrieval Strategy Benchmark

This record preserves live benchmark results across the PostgreSQL resets
required for each incompatible retrieval-unit representation. Each candidate
uses the Atlas corpus, `atlas-v3` (20 questions), top-five hybrid retrieval,
and reranking disabled.

## Gemini baseline — 2026-08-21

| Field | Value |
| --- | --- |
| Retrieval strategy | `passage_hybrid` |
| Corpus profile | `structural-token-v2`, `cl100k_base`, target/max/overlap `450/600/60` |
| Corpus units | 6 active documents; 23 `passage` units |
| Generation provider | Gemini `gemini-3.1-flash-lite`, JSON-schema mode, temperature 0 |
| Embedding provider | Gemini `gemini-embedding-2`, 768 dimensions, `retrieval-prefix-v1` |
| Evaluation run | `2d5d8bb3-85db-498e-bf2c-f31f52932799` |
| Dataset | `atlas-v3` (20 questions) |
| Started / completed | 2026-08-21 06:03:08 / 06:07:25 UTC |

| Top-5 hit rate | MRR | Gold citation coverage | Median / p95 latency | Failures |
| ---: | ---: | ---: | ---: | ---: |
| **1.0** | **0.848958** | **0.9375** | **6367.664 / 16125.401 ms** | **0** |

Additional quality metrics: citation structural validity `1.0`, citation
correctness `0.966667`, answer faithfulness `0.962963`, abstention accuracy
`0.9`, and facet abstention accuracy `0.837209`.

This is the comparison baseline only, not a selected winner. Benchmark
`sentence_expanded` and `parent_child_merged` on their own freshly reset,
reingested Gemini corpora before applying the agreed selection order: MRR,
then gold citation coverage, then lower median latency.
