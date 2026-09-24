# Loop Contract

## Purpose
1. Docling-Only PDF Parsing: execute `specs/001-docling-only-pdf/tasks.md` (T001–T025) until every PDF is parsed only by Docling, pypdf is fully removed, the error contract in `contracts/ingestion-pdf.md` holds, and the README, AGENTS.md, and `evaluation/parser_comparison.md` describe Docling-only behavior. Every done-criterion below must be confirmed by the independent checker.

## Done-criteria
| ID | Criterion (checkable) | How the checker verifies it | Status |
|----|-----------------------|-----------------------------|--------|
| D1 | `api/pyproject.toml` declares `"pypdfium2==5.13.0"` and does not declare `pypdf`. The built API image has no `pypdf` module. | `grep -n "pypdf" api/pyproject.toml` shows only the `pypdfium2==5.13.0` line. After `docker compose build api`, `docker compose run --rm --no-deps api python -c "import importlib.util as u; assert u.find_spec('pypdf') is None; import pypdfium2"` exits 0. | checker-pass |
| D2 | No pypdf or parser-selection references remain outside historical records. | `grep -rniI "pypdf\b\|pdf_parser\b\|PDF_PARSER\|PDF_PARSER_PROFILES\|ocr_not_supported\|_reconstruct_pdf_lines\|compare_pdf_parsers" api/src api/pyproject.toml api/tests scripts web/src .env.example README.md AGENTS.md` returns no matches. Allowed exception: the `"pdf_parser"` key of the corpus-profile dict in `profiles.py` and in tests that assert it; the checker confirms each remaining hit is that key. `scripts/compare_pdf_parsers.py` does not exist. | checker-pass |
| D3 | The API test suite passes. | `make test-api` exits 0. The output includes the tests `test_encrypted_pdf_returns_password_error`, `test_corrupt_pdf_returns_parser_specific_error`, `test_pdf_without_extractable_text_is_reported`, `test_non_pdf_sources_skip_worker_thread`, `test_pdf_parser_dispatches_to_docling`, `test_docling_parse_timeout_is_sanitized`, `test_corpus_profile_includes_pdf_parser_contract`, and `test_docling_reports_scanned_empty_pdf_without_text` (check with `pytest -q -rA` or `--collect-only`). | checker-pass |
| D4 | The web tests and the production build pass. | `make test-web` exits 0, and `docker compose run --rm web npm run build` exits 0. `web/src/components/IngestionStatus.tsx` maps `pdf_no_extractable_text` and has no `ocr_not_supported` entry. | checker-pass |
| D5 | Real Docling parses the Atlas PDF and the scanned fixture, with region locators only. | Run the quickstart step 4 command. Both `/workspace/sample_data/atlas/04-q3-planning.pdf` and `tests/fixtures/pdf/scanned-english.pdf` report more than 0 blocks and exactly `{'pdf_region'}`. | checker-pass |
| D6 | The PDF error contract holds against real files, with sanitized messages. | The checker writes its own probe, not the maker's tests, and runs it in the `api` container. The probe builds a reportlab user-password PDF, a corrupt-bytes file, and a blank one-page PDF, and calls `parse_document` on each. Expected codes: `pdf_password_protected`, `pdf_parse_failed`, `pdf_no_extractable_text`. Each has `retryable is False`, and no message contains `docling`, `PDFium`, or a file path. | checker-pass |
| D7 | Non-PDF behavior is unchanged. | `git diff` shows no edits to the Markdown, text, or DOCX parse functions in `parsers.py` or to their existing tests. `test_non_pdf_sources_skip_worker_thread` passes. A `.md` source with `model_timeout_seconds` near 0 does not raise `pdf_parse_timeout`. | checker-pass |
| D8 | The corpus profile and settings are Docling-only. | In the container, `resolve_corpus_profile("baseline","passage_hybrid")["pdf_parser"] == {"name":"docling","version":"2.130.0","ocr":"tesseract-eng","layout":"docling-layout-v1"}` and matches `CURRENT_CHUNKING_PROFILE["pdf_parser"]`. `Settings()` has no `pdf_parser` attribute. Calling `resolve_corpus_profile` with 3 positional arguments raises `TypeError`. | checker-pass |
| D9 | The frozen contracts and the file-size rule hold. | The signatures of `parse_document`, `ParsedDocument`, `_SourceBlock`, and the chunker are unchanged (`test_frozen_parser_and_chunker_contract` passes). Every hand-written file the loop touched is under 500 lines (`wc -l`). | checker-pass |
| D10 | The README states the Docling PDF behavior and contains no false PDF claims. | Read the README sections Key Features, Technology Stack, Installation, Privacy & Limitations, and Trade-offs. They must state: Docling does layout, table, and multi-column parsing; scanned English PDFs go through local OCR; models are bundled at build time with no runtime download; the approximate model and image size; encrypted PDFs are unsupported; region locators are stored but not highlighted. They must not say scanned PDFs are rejected, "embedded text" only, or that tables and multi-column text are out of scope. | checker-pass |
| D11 | AGENTS.md and the comparison record are updated. | AGENTS.md has a "Docling PDF parsing" heading without "(pdf-improvement branch)", no "Default remains `pypdf`", and a "PDF quality gate" section with the targets abstention ≥ 0.90 and conflict ≤ 0.05. `evaluation/parser_comparison.md` keeps the original table and JSON records, has a "Decision (2026-09-24)" section with the gap values (0.85/0.90 and 0.10/0.05), and has no runnable `--parser pypdf` command. | checker-pass |
| D12 | After the reset and reingest, benchmark SC-003 holds. **Human-gated**: the PostgreSQL reset needs explicit user approval, and the run uses the live Gemini provider. | After approval, run quickstart step 5. The results record in `evaluation/parser_comparison.md` shows top-five retrieval ≥ 1.00 and citation correctness ≥ 1.00 with a run_id. The checker cross-checks the run_id against the evaluation API or DB. SC-006 (abstention and conflict) is recorded as met or open; it is not blocking. | human-signed (owner waiver 2026-09-24; checker uncertain, see DEBT-001) |
| D13 | No secrets or unrelated files are staged or changed. | `git status` and `git diff --cached --name-only` show that `.env.gemini.bak`, `.env`, and any key or token files are not staged. The pre-existing `.gitignore` modification and `docs/superpowers/specs/2026-08-19-ingestion-chunking-correctness-design.md` are untouched by the loop. | checker-pass |

Statuses: pending → maker-ready → checker-pass | checker-fail → human-signed.

## Budget
- Max iterations: 15
- Iterations run: 6
- Isolation: none. This overrides the config default `worktree`. Reason: Docker Compose bind-mounts the main checkout and derives the project name and volumes from the directory, so a worktree would build a separate stack and database. The `specs/` state is also untracked, so it would be missing in a new worktree. Iterations run serially, so there are no collisions.
- Per-iteration scope: one tasks.md phase, or a coherent subset of one, per iteration. Each iteration ends with its phase's verification commands recorded in `iterations.md`.

## Roles
- Maker: `claude-sonnet-5`. Produces work toward the criteria (/speckit.loop.run). This overrides the AGENTS.md default maker (Luna High), as the user specified on 2026-09-24.
- Checker: `claude-opus-5.5` (model ID `claude-opus-5-5`). The independent, adversarial grader (/speckit.loop.check). It MUST be a separate agent or session from the maker. Votes required: 1.
- Closing gate: `/speckit-loop-guard` with human sign-off. It is the only command that can close the loop (AGENTS.md).

## Allowed tools / connectors
- Core Spec Kit workflow, plus `make test-api`, `make test-web`, and `docker compose build|run|exec|up|stop` for the `api`, `web`, and `db` services.
- Read-only git: `status`, `diff`, `log`, `show`. No commits, pushes, force pushes, or branch changes by maker or checker unless the user authorizes them.
- `grep`, `wc`, and file read/edit inside the repository.
- Live Gemini provider and the PostgreSQL reset: only for D12, only after explicit user approval. Never `docker compose down -v`. `live_provider` contract tests stay excluded.
- No new dependencies beyond the approved `pypdfium2==5.13.0`. No schema migrations.

## Automation trigger
- Manual: `/speckit.loop.run` (maker), then `/speckit.loop.check` (checker, in a separate session), then `/speckit-loop-guard` (human).

## Guardrails
- Human sign-off required before done: true
- Comprehension debt tracked: true
- Open blocking debt blocks done: true
- Checker must pass before done: true (independent, adversarial; default to fail when uncertain)
- Maker must not hand a red increment to the checker (AGENTS.md loop sensor gates).

## State
- Phase: done
- Last updated: 2026-09-24
