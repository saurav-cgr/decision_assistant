# Research: Docling-Only PDF Parsing

**Feature**: [spec.md](./spec.md) | **Date**: 2026-09-24

The findings below come from reading the code on `pdf-improvement` (commit `9e72588`) and from probes run inside the `api` image with Docling 2.130.0.

## R1. Where pypdf and the parser choice live today

**Decision**: Remove every item in the table. Keep only the Docling code.

| Location | What exists | Action |
|---|---|---|
| `api/pyproject.toml` | `pypdf==5.9.0` runtime dependency | Remove. Only `decision-assistant` requires it (verified in the image). |
| `ingestion/parsers.py` | `from pypdf import ...`, `_parse_pypdf_document`, `_reconstruct_pdf_lines`, and the `pdf_parser` branch in `_parse_pdf_document` | Remove the pypdf imports, `_parse_pypdf_document`, and `_reconstruct_pdf_lines`. `_parse_pdf_document` always calls the Docling path. Keep `_normalize_extracted_text`, because `docling_parser.py` uses it. |
| `ingestion/service.py` | `_parse_for_ingestion` uses the worker thread and timeout only when `pdf_parser == "docling"` | Use the worker thread and timeout for every `.pdf` file. Parse other suffixes synchronously, as today in the default mode. |
| `ingestion/profiles.py` | `PDF_PARSER_PROFILES` has two entries; `resolve_corpus_profile(..., pdf_parser="pypdf")`; `CURRENT_CHUNKING_PROFILE` resolves to pypdf | Replace with one `PDF_PARSER_PROFILE` constant for Docling. Remove the `pdf_parser` parameter. `CURRENT_CHUNKING_PROFILE` then embeds Docling. |
| `config.py` | `pdf_parser: str = "pypdf"` and its validator | Remove the field and the validator. `extra="ignore"` already tolerates a leftover `PDF_PARSER` env var, and the spec requires no stale-config handling. |
| `main.py`, `retrieval/router.py`, `answering/router.py`, `evaluation/router.py`, `documents/router.py` | Pass `settings.pdf_parser` to `resolve_corpus_profile` | Remove the argument (5 call sites). |
| `scripts/compare_pdf_parsers.py` | `--parser` with `choices=("pypdf", "docling")` | Delete the script. With one parser there is nothing to compare, and `compare_retrieval_strategies.py` already covers benchmark runs. `parser_comparison.md` keeps the historical records. |
| `scripts/compare_retrieval_strategies.py` | Calls `resolve_corpus_profile` with the pypdf default | Needs no change once the default becomes Docling. The profile then matches a Docling corpus (this fixes a latent mismatch). |
| `.env.example` | `PDF_PARSER=pypdf` | Remove the line. |
| Tests | See R5 | Rewrite or remove the affected tests. |

**Alternatives considered**: Keep `pdf_parser` as a validated `Literal["docling"]` setting. Rejected: the spec removed stale-config handling, and a one-value option adds surface with no value.

## R2. Password-protected PDF detection without pypdf

**Finding**: Docling reports encrypted and corrupt files with the same failure: `docling-parse could not load document <hash>: Failed to load document with key ...`. The message text cannot tell them apart. With pypdf removed, `pdf_password_protected` would silently collapse into `pdf_parse_failed`, which violates FR-004.

A probe with pypdfium2 5.13.0 (already installed as a Docling dependency; `docling-slim` requires `pypdfium2>=4.30.0,!=4.30.1,<6.0.0`) gave these results:

- User-password PDF: `PdfiumError: Failed to load document (PDFium: Incorrect password error).`
- Corrupt bytes: `PdfiumError: Failed to load document (PDFium: Data format error).`

**Decision**: Add a cheap PDFium preflight before Docling conversion:

- An `Incorrect password` error maps to `pdf_password_protected`.
- Any other preflight failure maps to `pdf_parse_failed`.

Declare `pypdfium2==5.13.0` as a direct pinned dependency. It is already in the image, so the image size does not change. The user approved this on 2026-09-24 (AGENTS.md: new dependencies).

**Behavior change (accepted)**: A PDF that has only an owner password (restricts printing or copying but opens without a password) no longer fails. pypdf `is_encrypted` rejected those files; PDFium opens them, and Docling can parse them. Only files that cannot be opened are "password-protected".

**Alternatives considered**:
- Scan the raw bytes for `/Encrypt`. Rejected: fragile, and it rejects owner-password-only files that are readable.
- Import pypdfium2 transitively without declaring it. Rejected: an undeclared import breaks silently when Docling changes its extras.
- Collapse encrypted files into `pdf_parse_failed`. Rejected: this violates FR-004 and removes an actionable user message.

## R3. PDFs with no extractable text

**Finding**: A blank reportlab page and `tests/fixtures/scanned-empty.pdf` both convert successfully in Docling but yield zero blocks. Today that maps to `pdf_parse_failed` ("PDF could not be parsed"), which suggests corruption. The pypdf code `ocr_not_supported` becomes false, because OCR now runs.

**Decision**: When Docling succeeds with zero blocks, raise the new code `pdf_no_extractable_text` with the message "PDF contains no extractable text". Remove `ocr_not_supported` from the backend. In `web/src/components/IngestionStatus.tsx`, replace the `ocr_not_supported` message with a `pdf_no_extractable_text` message, and update `Workspace.test.tsx`. This is a display mapping only, so React stays within its layer.

**Alternatives considered**: Reuse `ocr_not_supported`. Rejected: its message is now false. Keep `pdf_parse_failed`. Rejected: it tells users the file is corrupt when it is blank.

## R4. Timeout and worker-thread scope

**Finding**: `_parse_for_ingestion` runs everything in a worker thread with `model_timeout_seconds` when Docling is selected. That includes `.md`, `.txt`, and `.docx`, and a timeout on those raises the misleading `pdf_parse_timeout`.

**Decision**: Apply the worker thread and timeout only to `.pdf` sources. Markdown, text, and DOCX keep the synchronous path. This matches the current default behavior and satisfies FR-012.

## R5. Test impact

| Test | Action |
|---|---|
| `unit/test_pdf_parser.py::test_pdf_line_reconstruction_joins_wrapped_sentences` | Remove, because the helper is removed. |
| `::test_pdf_parser_preserves_page_numbers_and_offsets`, `::test_explicit_pypdf_selection_preserves_legacy_pdf_pages`, `::test_pdf_pages_are_page_blocks_with_hard_boundaries` | Remove (pypdf-only behavior). The integration fixture test already covers offsets and `pdf_region` locators. |
| `::test_pdf_parser_dispatches_to_docling` | Keep. Drop the `config.get_settings` monkeypatch; dispatch is unconditional. |
| `::test_docling_parse_runs_in_worker_thread`, `::test_docling_parse_timeout_is_sanitized` | Keep. Drop `pdf_parser` from the fake settings. Add a case that non-PDF sources skip the worker thread. |
| `::test_pdf_without_embedded_text_requires_ocr` | Rewrite: expect `pdf_no_extractable_text`. Stub the conversion result with zero items so the unit test stays offline and fast. Add a real-Docling case to the integration test. |
| `::test_encrypted_pdf_returns_password_error` | Rewrite: build the encrypted fixture with `reportlab.lib.pdfencrypt` instead of `pypdf.PdfWriter`. This exercises the preflight with no conversion. |
| `::test_corrupt_pdf_returns_parser_specific_error` | Keep. The preflight maps the failure to `pdf_parse_failed`. |
| `unit/test_chunking_profiles.py` | Replace the pypdf and parser-selection tests with: the corpus profile embeds the Docling identity, and `Settings` has no `pdf_parser`. |
| `integration/test_docling_pdf_ingestion.py` | Drop the settings monkeypatch. Add a blank or scanned-empty case expecting `pdf_no_extractable_text`. |
| `unit/test_chunking.py` and `unit/test_evaluation_service.py` (tests that use `pdf_page`) | Keep. They cover read-side and page-level gold matching (FR-005). |
| `web` tests that use `pdf_page` | Keep (citation display of page locators). |

## R6. Read-side `pdf_page` support

**Decision**: Keep `pdf_page` handling in `chunking.py` aggregation, `retrieval/provenance.py`, `evaluation/service.py` gold matching, and `web/src/components/CitationList.tsx`. The gold locators in `evaluation/questions.json` (5 occurrences) are page-level. AGENTS.md requires page-level gold locators to match `pdf_region` passages. The chunking branch is source-neutral and harmless.

**Alternatives considered**: Rewrite the gold locators as regions. Rejected: that is out of scope, and page-level gold matching is the intended contract.

## R7. Documentation scope

**Decision**:

- **README**: Fix the Key Features ingestion row, the Privacy & Limitations "Supported formats" paragraph, and the Trade-offs PDF line. Add a short "PDF parsing" note to Installation or the Technology Stack section:
  - The Docling models are bundled at build time.
  - Parsing runs offline.
  - Model weights add about 701 MB to an image of about 2.6 GB.
- **AGENTS.md**:
  - Rename "Docling PDF parsing (pdf-improvement branch)" to "Docling PDF parsing".
  - Remove the pypdf and parser-switch rules.
  - Keep the offline, local-only, sanitized-error, and locator rules.
  - Replace "Parser comparison evaluation" with the forward quality gate (SC-006).
- **`evaluation/parser_comparison.md`**: Append a "Decision" section: pypdf removed on 2026-09-24, and the gate waived by the owner. Record the open follow-up (abstention 0.85 against target 0.90; conflict 0.10 against target 0.05). Remove the obsolete pypdf reproduction commands, and keep the raw records.
- Historical docs under `docs/superpowers/` are not rewritten (spec assumption).

## R8. Corpus reset

**Decision**: No schema migration. `CURRENT_CHUNKING_PROFILE` changes from pypdf to Docling, so an existing development corpus built under pypdf needs a reset and reingest. The spec requires no stale-corpus handling. The existing generic guard stays untouched. The reset runs once for SC-003 validation, with explicit approval (quickstart step 5).
