# Quickstart: Validate Docling-Only PDF Parsing

Run everything from the repository root through Docker Compose.

## 1. Dependency and reference sweep (SC-002)

```bash
grep -rniI "pypdf\b\|pdf_parser\|PDF_PARSER\|ocr_not_supported" \
  api/src api/pyproject.toml api/tests scripts web/src .env.example README.md AGENTS.md
```

Expected: no matches. Historical records in `evaluation/parser_comparison.md` and `docs/superpowers/` are excluded on purpose. `pypdfium2` matches are allowed (see research R2).

## 2. Rebuild the API image (dependency change)

```bash
docker compose build api
docker compose run --rm --no-deps api python -c "import importlib.util as u; assert u.find_spec('pypdf') is None; import pypdfium2"
```

Expected: exits 0.

## 3. Unit and integration tests (SC-001, SC-005)

```bash
make test-api
make test-web
docker compose run --rm web npm run build
```

Expected: all pass. The following tests must be green:
- `tests/integration/test_docling_pdf_ingestion.py`: 4 fixtures ingest with `pdf_region` locators, and a blank PDF returns `pdf_no_extractable_text`.
- `tests/unit/test_pdf_parser.py`: the encrypted, corrupt, empty, dispatch, timeout, and non-PDF synchronous-path tests.
- The Markdown, text, and DOCX parser tests, unchanged.

## 4. Docling smoke conversion (AGENTS.md loop gate)

```bash
docker compose run --rm --no-deps api python -c "
from pathlib import Path
from decision_assistant.ingestion.parsers import parse_document
for p in ['/workspace/sample_data/atlas/04-q3-planning.pdf', 'tests/fixtures/pdf/scanned-english.pdf']:
    d = parse_document(Path(p)); print(p, len(d.blocks), {b.locator['kind'] for b in d.blocks})
"
```

Expected: both files report blocks, with locator kinds `{'pdf_region'}`.

## 5. Reset, reingest, and benchmark (SC-003, SC-006). Destructive to PostgreSQL. Ask first.

First, reset PostgreSQL by following the first five commands of the README section "Corpus Reset & Reingestion", from `docker compose stop` through `docker compose up`. Skip the `ingest_corpus.py` command, because the script below ingests the corpus itself. Then run the benchmark, which reingests Atlas and evaluates it:

```bash
docker compose run --rm --no-deps api python /workspace/scripts/compare_retrieval_strategies.py \
  --strategy passage_hybrid --source-directory /workspace/sample_data/atlas \
  --api-origin http://api:8000
```

The script checks that the reingested corpus profile matches `CURRENT_CHUNKING_PROFILE`, which now embeds Docling. Expected:
- Top-five retrieval ≥ 1.00 and citation correctness ≥ 1.00 (SC-003, blocking).
- Record abstention accuracy and conflict rate in `evaluation/parser_comparison.md` against the SC-006 follow-up targets (≥ 0.90 and ≤ 0.05). This step is non-blocking.

## 6. README walkthrough (SC-004)

Read the Key Features, Installation, Privacy & Limitations, Troubleshooting, and Trade-offs sections. Every PDF claim must match steps 3–5, and no claim may name pypdf.
