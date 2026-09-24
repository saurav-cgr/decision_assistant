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

Run from the repository root. Keep the database reset between parser runs; never compare both parsers in one corpus.

```bash
docker compose stop api web
docker compose exec -T db sh -lc \
  'dropdb --if-exists --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose run --rm api alembic upgrade head
PDF_PARSER=pypdf docker compose up -d api --wait
docker compose run --rm --no-deps api python /workspace/scripts/compare_pdf_parsers.py \
  --parser pypdf --source-directory /workspace/sample_data/atlas \
  --api-origin http://api:8000 --timeout 1800
```

Repeat the reset, migration, and API start with `PDF_PARSER=docling`, then run the same command with `--parser docling`.
