# PDF parser comparison

Benchmark date: 2026-09-24

Corpus: `sample_data/atlas`

Questions: `evaluation/questions.json` (`atlas-v3`, 20 questions)

Providers: Gemini generation and embedding; reranking disabled; baseline chunking and `passage_hybrid` retrieval.

Image: `decision-assistant-api`, 2,607,408,432 bytes. Bundled `/opt/docling-models`: 701,229,878 bytes. Gemini model weights are remote and are not bundled in the image.

Each row used a fresh PostgreSQL database reset, migration, API restart with the selected parser, and complete corpus reingestion before evaluation. The runner verifies the parser profile in both ingestion output and the evaluation corpus snapshot.

| Parser | Passages | Ingest seconds | Top-five retrieval | Citation structural validity | Citation correctness | Abstention accuracy | Conflict rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| pypdf 5.9.0 | 23 | 44.202 | 1.00 | 1.00 | 0.9655 | 0.90 | 0.05 |
| Docling 2.130.0 | 28 | 41.383 | 1.00 | 1.00 | 1.00 | 0.85 | 0.10 |

Conflict rate is the fraction of evaluated answers whose generated output contained one or more conflicts. The evaluation service's aggregate abstention score is the exact expected-outcome match rate.

## Raw run records

The JSON records below are the machine-readable runner outputs. `run_id`, provider profiles, corpus snapshots, aggregate metrics, and question count are retained so each result can be audited against the separate reset run.

```json
{
  "parser": "pypdf",
  "run_id": "4d28b17d-3fde-489f-bfa6-da07560349af",
  "profile_verified": true,
  "corpus_snapshot_documents": 6,
  "passage_count": 23,
  "ingest_seconds": 44.202,
  "dataset_version": "atlas-v3",
  "corpus_profile": {"pdf_parser": {"name": "pypdf", "version": "5.9.0"}, "retrieval_unit_strategy": "passage_hybrid"},
  "generation_profile": {"provider": "gemini", "model": "gemini-3.1-flash-lite"},
  "embedding_profile": {"provider": "gemini", "model": "gemini-embedding-2"},
  "metrics": {"top_five_hit_rate": 1.0, "citation_structural_validity": 1.0, "citation_correctness": 0.9655172413793104, "abstention_accuracy": 0.9, "conflict_rate": 0.05}
}
```

```json
{
  "parser": "docling",
  "run_id": "37dff8d6-e167-4f9a-9441-a8e120dcb632",
  "profile_verified": true,
  "corpus_snapshot_documents": 6,
  "passage_count": 28,
  "ingest_seconds": 41.383,
  "dataset_version": "atlas-v3",
  "corpus_profile": {"pdf_parser": {"name": "docling", "version": "2.130.0"}, "retrieval_unit_strategy": "passage_hybrid"},
  "generation_profile": {"provider": "gemini", "model": "gemini-3.1-flash-lite"},
  "embedding_profile": {"provider": "gemini", "model": "gemini-embedding-2"},
  "metrics": {"top_five_hit_rate": 1.0, "citation_structural_validity": 1.0, "citation_correctness": 1.0, "abstention_accuracy": 0.85, "conflict_rate": 0.1}
}
```

## Reproduction

pypdf and `scripts/compare_pdf_parsers.py` were removed on 2026-09-24; Docling is
now the only supported PDF parser, and there is nothing left to compare between
parsers. The historical pypdf run recorded above can be reproduced only by
checking out git history before this change.

## Decision (2026-09-24)

Docling is the only PDF parser. The former parity gate was waived by the
project owner: Docling leads on citation correctness (1.00 vs 0.9655) but
trails on abstention accuracy (0.85 vs 0.90) and conflict rate (0.10 vs 0.05).

Open follow-up gate (spec SC-006): abstention accuracy ≥ 0.90 and conflict
rate ≤ 0.05 on the Atlas benchmark, measured after a full Docling reset and
reingestion.

## D12 reset-and-reingest benchmark (2026-09-24)

Full PostgreSQL reset (`dropdb`/`createdb`, `alembic upgrade head`), complete
Atlas reingestion under the Docling-only profile, live Gemini generation and
embedding, reranking disabled, `passage_hybrid` strategy. `run_id`
`d319e454-1d8f-48cb-9ce2-4785eeebf70c`. Corpus: 6 documents, 28 passages, all
active `DocumentVersion.chunking_profile` rows confirmed matching
`CURRENT_CHUNKING_PROFILE` (queried directly in Postgres; the evaluation run's
own `corpus_snapshot` confirms the same).

| Metric | Result | SC target | Met |
|---|---:|---:|---|
| Top-five retrieval | 1.00 | ≥ 1.00 (SC-003, blocking) | yes |
| Citation correctness | 0.9643 | ≥ 1.00 (SC-003, blocking) | **no** |
| Abstention accuracy | 0.80 | ≥ 0.90 (SC-006, non-blocking) | no |
| Conflict rate | 0.05 | ≤ 0.05 (SC-006, non-blocking) | yes |

The single citation miss is on `atlas-001`, a Markdown source (`01-product-plan.md`),
not a PDF: the judge model marked one claim as unsupported because the source
passage confirms the postponement reason but does not restate the month
("May"), a date-attribution nuance in the judge's grading, not a retrieval or
citation-plumbing defect. It is not attributable to the Docling parser change.
The historical pypdf baseline above also missed this same SC-003 bar
(0.9655, not 1.00), so a sub-1.00 citation-correctness score already existed
before this change and is not a regression introduced by Docling.

A first run of this benchmark (before the run above) hit a transient
`Model provider unavailable` failure on one question (`atlas-010`) and was
discarded rather than counted; the run recorded here is the clean rerun.

SC-003's literal ≥ 1.00 bar is not met on this run. This is reported as-is,
without a retry-until-passing loop, since repeated resampling against a
judge-model threshold this tight would not be a meaningful signal.

**Waived by the project owner (2026-09-24)**, same basis as the earlier
SC-006 waiver: the single miss is on a non-PDF (Markdown) source, is a
judge date-attribution nuance rather than a retrieval or citation-plumbing
defect, and the pre-Docling pypdf baseline missed this same bar too
(0.9655). D12 is treated as met.
