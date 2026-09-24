# Comprehension Debt & Sign-off

Every change the loop makes that a human has not yet understood is debt. Debt is
acknowledged, not deleted. The loop may not declare "done" while blocking debt is open.

## Open debt
| ID | Iteration | What changed | Why it needs human eyes | Severity | Status |
|----|-----------|--------------|-------------------------|----------|--------|
| DEBT-001 | 6 | D12 is marked met by a user waiver of SC-003 citation correctness (0.9643 vs ≥ 1.00, run d319e454). | The waiver was given in the maker session, and the checker cannot verify it. The owner must confirm it at `/speckit-loop-guard`. Also: `scripts/compare_retrieval_strategies.py` cannot verify the corpus, because `ActiveVersionDetail` never serializes `chunking_profile` (pre-existing, out of scope). | blocking | acknowledged 2026-09-24 |
| DEBT-002 | 3 | `docling_parser.py`: new `_preflight_pdf` uses pypdfium2 (new dependency) to route "password" PdfiumErrors to `pdf_password_protected` and others to `pdf_parse_failed`; zero blocks raise `pdf_no_extractable_text`. | This is the error contract users see. The match is on the substring "password" in a PDFium message. PDFs with only an owner password are now accepted, and no test covers that. | medium | acknowledged 2026-09-24 |
| DEBT-003 | 3 | `ingestion/service.py`: the worker thread and `model_timeout_seconds` timeout now apply only to `.pdf` sources (keyed on the file suffix). | Non-PDF parses no longer run in a worker thread, so a PDF mislabeled with another extension would bypass the timeout. | low | acknowledged 2026-09-24 |
| DEBT-004 | 3 | `pdf_parser` setting, `PDF_PARSER` env var, and parser dispatch removed (`config.py`, `profiles.py`, routers, `main.py`, `.env.example`); `resolve_corpus_profile` now takes 2 args. | A leftover `PDF_PARSER` in someone's `.env` is ignored silently (`extra="ignore"`). This was a deliberate user decision (M-002), but it changes behavior with no warning. | low | acknowledged 2026-09-24 |
| DEBT-005 | 3 | Collateral test edits: `test_chunking.py` renamed a test to `..._pdf_region_locator_kind`; `test_evaluation_fixture.py` added a `_locator_matches` helper. | These are outside the tasks.md list. The helper copies `evaluation/service.py::_locator_covers` logic, so the two can drift apart. | low | acknowledged 2026-09-24 |
| DEBT-006 | 4 | README, AGENTS.md, and `evaluation/parser_comparison.md` rewritten for Docling-only behavior; `scripts/compare_pdf_parsers.py` deleted. | These are claims made to readers: the image-size figures (~701 MB models, ~2.6 GB image), scope statements, and the historical pypdf numbers now reproducible only from git history. | low | acknowledged 2026-09-24 |

## Sign-off log
| Date | Criterion / scope | Signed off by | Note |
|------|-------------------|---------------|------|
| 2026-09-24 | Whole loop (D1–D13, DEBT-001 to DEBT-006) | saurav-cgr (project owner) | The owner waived the D12 SC-003 citation target (0.9643 vs ≥ 1.00; the miss is on the Markdown atlas-001, not a PDF). The owner accepted DEBT-002 (owner-password PDFs allowed, "password" message match), DEBT-003 (timeout scoped to .pdf), and the D2 `PDF_PARSER_PROFILE` naming, confirmed a real-PDF ingest after the reset, and states they can explain every change. SC-006 abstention (0.80 vs 0.90) remains an open non-blocking follow-up. |
