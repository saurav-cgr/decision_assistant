# Chunking Profile Comparison & Benchmark

**Applies to:** `docs/superpowers/plans/2026-08-19-ingestion-chunking-correctness.md`, Step 4–5.

The goal is to select a default `structural-token-v2` chunking profile with
reproducible Atlas benchmark evidence. Each candidate preset is benchmarked on
its **own isolated, freshly reingested corpus**; the profile that wins the
selection rule becomes the application default.

## Presets

| Preset | Target | Max | Overlap | Algorithm |
| --- | ---: | ---: | ---: | --- |
| `baseline` (default) | 450 | 600 | 60 | `structural-token-v2` |
| `compact` | 250 | 350 | 40 | `structural-token-v2` |
| `expanded` | 700 | 900 | 80 | `structural-token-v2` |

The exact profile is resolved from the single source of truth in
`api/src/decision_assistant/ingestion/profiles.py`
(`resolve_chunking_profile`), never duplicated in tooling.

## Comparison command

`scripts/compare_chunk_profiles.py` accepts one preset and emits a
machine-readable result reusing the existing corpus-ingestion script and the
evaluation service (no second retrieval implementation).

```bash
# Validate arguments and emit a planned result (no API/DB access)
docker compose run --rm api \
  python /workspace/scripts/compare_chunk_profiles.py --preset baseline --dry-run

# Full run against a freshly reset, reingested corpus for one preset
docker compose run --rm api \
  python /workspace/scripts/compare_chunk_profiles.py --preset compact \
  --api-origin http://api:8000
```

Output contains **only non-secret configuration** (the exact profile) and
metrics:

```json
{
  "status": "completed",
  "preset": "compact",
  "profile": {
    "algorithm": "structural-token-v2",
    "encoding": "cl100k_base",
    "target_tokens": 250,
    "max_tokens": 350,
    "overlap_tokens": 40
  },
  "passage_count": 18,
  "metrics": {
    "top_five_hit_rate": 0.85,
    "mean_reciprocal_rank": 0.62,
    "citation_structural_validity": 0.93,
    "citation_correctness": 0.71,
    "gold_citation_coverage": 0.55,
    "abstention_accuracy": 0.96,
    "facet_abstention_accuracy": 0.9,
    "answer_faithfulness": 0.88,
    "median_latency_ms": 1420.5,
    "p95_latency_ms": 2700.0,
    "question_failures": 1
  }
}
```

## Isolated / reset corpus procedure (one per preset)

Changing the chunking profile is **not migratable**: the corpus-profile guard
returns `corpus_reset_required` for any mismatch. Each preset therefore needs a
dedicated reset/reingestion cycle against PostgreSQL only (never
`docker compose down -v`), preserving `uploads_data`, `ollama_data`, and
`web_node_modules`.

1. Confirm the Atlas sources under `sample_data/atlas` are reproducible and the
   correct database is targeted.
2. Stop only API and web services.
3. Reset PostgreSQL only, migrate, and reingest Atlas with the API running under
   `CHUNKING_PROFILE_PRESET=<preset>`.
4. Run `compare_chunk_profiles.py --preset <preset>` and save the result.
5. Verify `/ready` and that no `corpus_reset_required` is reported.

Run this entire cycle once for each of `baseline`, `compact`, and `expanded`.

## Selection rule

- The preset with the **highest top-five retrieval hit rate**
  (`metrics.top_five_hit_rate`) becomes the default.
- On a tie, **retain `baseline`**.
- MRR, citation metrics, passage count, and latency are recorded for review but
  do not override the selection metric.

After a winner is chosen, repeat the approved reset/reingestion once with that
preset as the application default so the final corpus matches the shipped
configuration, then verify `/ready` and the recorded benchmark.

## Results (2026-08-19)

Benchmarked on a freshly reset, reingested Atlas corpus per preset with live
Gemini (`atlas-v3`, 20 questions). `expanded` was **skipped**: both `baseline`
and `compact` already reached the maximum top-5 hit rate of 1.0, so `expanded`
could not change the outcome.

| Preset | Top-5 | MRR | Gold cit. cov. | Abstention acc. | Faithfulness | Med / p95 ms | Failures | Passages |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline` (450/600/60) | **1.0** | 0.786 | **0.75** | 0.85 | 1.0 | 3504 / 27766 | 0 | 23 |
| `compact` (250/350/40) | 1.0 | 0.786 | 0.688 | 0.85 | 1.0 | 6195 / 39949 | 0 | 23 |

**Selected default: `baseline`.** It ties `compact` on the selection metric
(top-5 hit rate = 1.0), and per the tie rule `baseline` is retained; it is also
slightly better on gold citation coverage and markedly faster on latency (the
latency gap is consistent with free-tier Gemini rate limiting).

The final database corpus was reset and reingested with the `baseline` preset
(the application default) and verified: `/ready` returns `{"status":"ready"}`
with no `corpus_reset_required`.
