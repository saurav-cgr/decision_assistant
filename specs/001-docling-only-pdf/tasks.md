---

description: "Task list for Docling-only PDF parsing"
---

# Tasks: Docling-Only PDF Parsing

**Input**: Design documents from `specs/001-docling-only-pdf/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ingestion-pdf.md, quickstart.md

**Tests**: Included. FR-007 requires tests for Docling-only dispatch and corpus profile contents. AGENTS.md requires focused coverage at the owning layer.

**Organization**: Tasks are grouped by user story. US1 (P1) removes pypdf. US2 (P2) updates the documentation.

**Approval gate**: Outside a `$speckit-loop`, complete one phase at a time. After each phase, stop and report the files changed, the verification run, and the risks. Then wait for `continue`. All paths are relative to the repository root. Run commands through Docker Compose.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 or US2 (from spec.md)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Declare pypdfium2 before the preflight uses it. pypdf stays installed until the pypdf code and tests are gone (T018). Removing it now would break `tests/unit/test_pdf_parser.py` imports before T004 removes them.

- [x] T001 In `api/pyproject.toml`, add `"pypdfium2==5.13.0",` in alphabetical order, after `"pypdf==5.9.0",` and before `"python-docx==1.2.0",`. Do not remove pypdf yet. The user approved this dependency on 2026-09-24 (research R2).
- [x] T002 Rebuild the API image with `docker compose build api`. Verify that `docker compose run --rm --no-deps api python -c "import importlib.metadata as m; print(m.version('pypdfium2'))"` prints `5.13.0`.

---

## Phase 2: Foundational (Blocking Prerequisites)

No separate foundational tasks. The `pdf_parser` setting drives parser dispatch in `parsers.py` and `service.py`. Removing it cannot land green without removing the pypdf path and its tests at the same time, so the profile and settings collapse is part of US1.

---

## Phase 3: User Story 1 - Every PDF is parsed by the single supported parser (Priority: P1) 🎯 MVP

**Goal**: Every PDF goes through Docling, and the pypdf code is gone. Password, corrupt, empty, OCR, layout, and timeout errors all map to sanitized, non-retryable codes (contracts/ingestion-pdf.md).

**Independent Test**: `make test-api` is green. `tests/integration/test_docling_pdf_ingestion.py` ingests all 4 fixtures with `pdf_region` locators. A blank PDF returns `pdf_no_extractable_text`. The quickstart step 4 smoke reports `{'pdf_region'}` for the Atlas PDF and the scanned fixture.

### Tests for User Story 1 ⚠️

> Write or update these first. They must fail before T008–T015.

- [x] T003 [P] [US1] In `api/tests/unit/test_chunking_profiles.py`:
  - Replace the `PDF_PARSER_PROFILES` import with `PDF_PARSER_PROFILE`.
  - Rewrite `test_corpus_profile_includes_pdf_parser_contract` to assert `resolve_corpus_profile("baseline", "passage_hybrid")["pdf_parser"] == PDF_PARSER_PROFILE` and `PDF_PARSER_PROFILE["name"] == "docling"`.
  - Delete the three-argument `"other"` parser `ValueError` case (about line 80).
  - In `test_settings_default_is_baseline`, replace `assert settings.pdf_parser == "pypdf"` with `assert not hasattr(settings, "pdf_parser")`.
  - Delete `test_settings_accepts_valid_pdf_parser` and `test_settings_rejects_invalid_pdf_parser`.
  - Also assert `CURRENT_CHUNKING_PROFILE["pdf_parser"]["name"] == "docling"`.
- [x] T004 [P] [US1] In `api/tests/unit/test_pdf_parser.py`, remove the pypdf tests:
  - Delete `from pypdf import PdfReader, PdfWriter` and `_reconstruct_pdf_lines` from the imports.
  - Delete `test_pdf_line_reconstruction_joins_wrapped_sentences`, `test_pdf_parser_preserves_page_numbers_and_offsets`, `test_explicit_pypdf_selection_preserves_legacy_pdf_pages`, and `test_pdf_pages_are_page_blocks_with_hard_boundaries`.
  - In `test_pdf_parser_dispatches_to_docling`, remove the `config.get_settings` monkeypatch and keep the `_parse_docling_pdf_document` stub.
  - In `test_docling_parse_runs_in_worker_thread` and `test_docling_parse_timeout_is_sanitized`, drop `pdf_parser="docling"` from the `SimpleNamespace` settings and keep `model_timeout_seconds`.
- [x] T005 [US1] In `api/tests/unit/test_pdf_parser.py`, rewrite and add error tests (depends on T004):
  - (a) `test_encrypted_pdf_returns_password_error`: build the file with `reportlab.pdfgen.canvas.Canvas(str(path), encrypt=reportlab.lib.pdfencrypt.StandardEncryption("secret", canPrint=0))`, draw one string, and save. Expect `code == "pdf_password_protected"` and `retryable is False`. Stub `docling.document_converter.DocumentConverter` so that the test fails if conversion is reached.
  - (b) Keep `test_corrupt_pdf_returns_parser_specific_error`, expecting `pdf_parse_failed`.
  - (c) Replace `test_pdf_without_embedded_text_requires_ocr` with `test_pdf_without_extractable_text_is_reported`: monkeypatch the converter to return a `SUCCESS` result whose document yields no items, and expect `code == "pdf_no_extractable_text"` and message `"PDF contains no extractable text"`.
  - (d) Add `test_non_pdf_sources_skip_worker_thread`: with `service.parse_document` stubbed to record the thread id, assert that `_parse_for_ingestion(Path("tests/fixtures/meeting.md"))` runs on the caller thread.
  - (e) Assert that no raised message contains `"docling-parse"` or `"PDFium"`.
- [x] T006 [P] [US1] In `api/tests/integration/test_docling_pdf_ingestion.py`, remove the `config.get_settings` monkeypatch and the `SimpleNamespace` and `config` imports if they become unused. Replace `assert error.code != "ocr_not_supported"` with a plain `raise`. Add `test_docling_reports_scanned_empty_pdf_without_text` on `tests/fixtures/scanned-empty.pdf`, expecting `DocumentParseError` with `code == "pdf_no_extractable_text"`.
- [x] T007 [US1] Run `docker compose run --rm api pytest tests/unit/test_chunking_profiles.py tests/unit/test_pdf_parser.py tests/integration/test_docling_pdf_ingestion.py -q`. Confirm that the new and rewritten tests fail for the expected reasons (missing preflight, missing code, or the settings field still present) before implementing.

### Implementation for User Story 1

- [x] T008 [US1] In `api/src/decision_assistant/ingestion/profiles.py`, replace the `PDF_PARSER_PROFILES` dict with the single constant `PDF_PARSER_PROFILE: dict[str, str] = {"name": "docling", "version": "2.130.0", "ocr": "tesseract-eng", "layout": "docling-layout-v1"}`. Remove the `pdf_parser` parameter and the "Unknown PDF parser" check from `resolve_corpus_profile`. Return `"pdf_parser": PDF_PARSER_PROFILE.copy()`. `CURRENT_CHUNKING_PROFILE` then embeds Docling automatically.
- [x] T009 [US1] In `api/src/decision_assistant/config.py`, remove the `PDF_PARSER_PROFILES` import, the `pdf_parser: str = "pypdf"` field, and the `_validate_pdf_parser` validator. Keep `extra="ignore"`, so a leftover `PDF_PARSER` env var is ignored (data-model: Settings).
- [x] T010 [US1] Remove the `settings.pdf_parser` argument from the `resolve_corpus_profile(...)` calls in `api/src/decision_assistant/main.py` (about line 223), `api/src/decision_assistant/retrieval/router.py` (about line 62), `api/src/decision_assistant/answering/router.py` (about line 68), `api/src/decision_assistant/evaluation/router.py` (about line 49), and `api/src/decision_assistant/documents/router.py` (about line 74).
- [x] T011 [P] [US1] In `.env.example`, remove the line `PDF_PARSER=pypdf`.
- [x] T012 [US1] In `api/src/decision_assistant/ingestion/parsers.py`:
  - Delete `from pypdf import PdfReader` and `from pypdf.errors import PdfReadError`.
  - Delete `_parse_pypdf_document` and `_reconstruct_pdf_lines`.
  - Make `_parse_pdf_document(path)` call `_parse_docling_pdf_document(path)` unconditionally, and remove its `get_settings` import.
  - Keep `_normalize_extracted_text`, `_heading_key`, `_assemble_document`, the `_docling_*` shims, and all frozen signatures (`parse_document`, `ParsedDocument`, `_SourceBlock`).
- [x] T013 [US1] In `api/src/decision_assistant/ingestion/docling_parser.py`, add `_preflight_pdf(path: Path) -> None`:
  - Import `pypdfium2` lazily inside the function.
  - Call `pypdfium2.PdfDocument(str(path))`, then `.close()`.
  - On `pypdfium2.PdfiumError` whose text contains `"password"` (case-insensitive), raise `DocumentParseError("pdf_password_protected", "Password-protected PDF files are not supported")` from the exception.
  - On any other `PdfiumError` or `OSError`, raise `DocumentParseError("pdf_parse_failed", "PDF could not be parsed")`.
  - Call `_preflight_pdf(path)` first in `parse_docling_pdf`, before building `PdfPipelineOptions`, and outside the broad `except Exception` block so that the codes are not remapped.
- [x] T014 [US1] In `api/src/decision_assistant/ingestion/docling_parser.py`, change the zero-block branch in `parse_docling_pdf` (`if not source_blocks:`) to raise `DocumentParseError("pdf_no_extractable_text", "PDF contains no extractable text")`.
- [x] T015 [US1] In `api/src/decision_assistant/ingestion/service.py`, change `_parse_for_ingestion` so that the `asyncio.to_thread` plus `asyncio.wait_for(..., timeout=get_settings().model_timeout_seconds)` path, with its `pdf_parse_timeout` mapping, runs when `source_path.suffix.lower() == ".pdf"`. All other suffixes call `parse_document(source_path)` synchronously. Remove the `pdf_parser` check.
- [x] T016 [P] [US1] Delete `scripts/compare_pdf_parsers.py` (research R1). Confirm that no other file imports it: `grep -rn "compare_pdf_parsers" --exclude-dir=node_modules .` should match only `evaluation/parser_comparison.md`, which T020 handles.
- [x] T017 [P] [US1] Web error display (contracts/ingestion-pdf.md, "Web display contract"):
  - In `web/src/components/IngestionStatus.tsx`, replace the `ocr_not_supported` entry in `parserErrors` with `pdf_no_extractable_text: "This PDF contains no readable text."`.
  - In `web/src/pages/Workspace.test.tsx` (about line 183), change the fixture error code to `pdf_no_extractable_text`, and update any assertion on the old message to the new message.
- [x] T018 [US1] Verify US1:
  - Run `make test-api`, `make test-web`, and `docker compose run --rm web npm run build`.
  - Remove `"pypdf==5.9.0",` from `api/pyproject.toml`, then rebuild with `docker compose build api`.
  - Run `docker compose run --rm --no-deps api python -c "import importlib.util as u; assert u.find_spec('pypdf') is None"`. Research found that only `decision-assistant` requires pypdf, so this must pass.
  - Record the image size with `docker image inspect decision-assistant-api --format '{{.Size}}'` for the README (T019).
  - Run `make test-api` again on the rebuilt image.
  - Run the quickstart step 4 Docling smoke conversion.
  - Keep `wc -l api/src/decision_assistant/ingestion/*.py` below 500 for every file.

**Checkpoint**: pypdf is gone. Every PDF path runs through Docling, and all error codes are covered. Stop for review.

---

## Phase 4: User Story 2 - README accurately describes Docling PDF support (Priority: P2)

**Goal**: The README, AGENTS.md, and the comparison record describe Docling-only behavior, with no false PDF claims.

**Independent Test**: The quickstart step 1 sweep finds no `pypdf`, `pdf_parser`, `PDF_PARSER`, or `ocr_not_supported` in the README or AGENTS.md. The step 6 walkthrough finds 0 contradictions.

- [x] T019 [P] [US2] Update `README.md` in five places:
  - **Key Features "Document ingestion" row**, about line 63: say PDFs are parsed locally with Docling (layout-aware reading order, tables, and multi-column text), scanned English PDFs go through local OCR, new PDF passages carry page and region locators, and encrypted, corrupt, and blank PDFs receive explicit errors.
  - **Technology Stack**: add Docling 2.130.0 with Tesseract English OCR, and pypdfium2 for the PDF preflight.
  - **Installation, "Build and start"**: note that the API image bundles Docling layout and table models at build time under `/opt/docling-models`, that PDF parsing never downloads models at runtime, and that the models add about 701 MB (image about 2.6 GB; use the T018 measurement if it differs).
  - **Privacy & Limitations "Supported formats" paragraph**, about line 319: replace the sentences that say scanned PDFs are rejected and that complex layout, tables, and multi-column text are out of scope. State that the formats are Markdown, text, DOCX, and PDF (digital or scanned English); that PDF parsing and OCR run locally; that encrypted and password-protected PDFs, macros, link following, and password recovery remain out of scope; and that PDF region locators are stored and returned but not visually highlighted.
  - **Trade-offs**, about line 343: replace "not pixel-perfect PDF coordinates" with a line saying Docling adds image size and ingest CPU in exchange for layout, table, and OCR support, and that region coordinates are stored but not highlighted yet.
- [x] T020 [P] [US2] Update `evaluation/parser_comparison.md`:
  - Keep the header, the table, and the raw JSON records unchanged as history.
  - Replace the "Reproduction" section with a note that pypdf and `scripts/compare_pdf_parsers.py` were removed on 2026-09-24, and that the historical pypdf run can be reproduced only from git history before this change.
  - Append a "Decision (2026-09-24)" section. It says Docling is the only PDF parser; the former parity gate was waived by the project owner because Docling leads on citation correctness (1.00 vs 0.9655) but trails on abstention accuracy (0.85 vs 0.90) and conflict rate (0.10 vs 0.05); and there is an open follow-up gate: abstention accuracy ≥ 0.90 and conflict rate ≤ 0.05 on the Atlas benchmark after full reingestion (spec SC-006).
- [x] T021 [P] [US2] Update `AGENTS.md` in four places:
  - Rename "## Docling PDF parsing (pdf-improvement branch)" to "## Docling PDF parsing".
  - In the "Parser contract is reset-required" bullet, replace the pypdf switching text: Docling is the only PDF parser; `resolve_corpus_profile` embeds its name, version, and OCR/layout options; and changing any of them invalidates the corpus and requires reset and reingest. Remove "Default remains `pypdf` during comparison."
  - In the "Locator kinds" bullet, replace "`pypdf` emits `pdf_page`" with: new ingestion emits only `pdf_region`, and `pdf_page` stays a supported read and gold-locator kind that matches region passages by page.
  - Replace the "## Parser comparison evaluation" section with "## PDF quality gate": record the SC-006 follow-up targets, name `evaluation/parser_comparison.md` as the audit record, and say that a Docling upgrade or option change requires a reset-and-reingest benchmark recorded there. In the loop sensor gates, change "English digital + scanned" smoke wording only if it mentions pypdf. Keep the no-runtime-download, local-only, sanitized-error, and PDF UI scope rules.
- [x] T022 [US2] Run the quickstart step 1 sweep: `grep -rniI "pypdf\b\|pdf_parser\|PDF_PARSER\|ocr_not_supported" api/src api/pyproject.toml api/tests scripts web/src .env.example README.md AGENTS.md`. Expected: no matches (`pypdfium2` does not match `pypdf\b`). Then do the step 6 README walkthrough against the Phase 3 behavior.

**Checkpoint**: The docs match the behavior. Stop for review.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [x] T023 Run the full gates: `make test-api`, `make test-web`, and `docker compose run --rm web npm run build`. Before any commit, recheck the staged files for secrets, and never stage `.env.gemini.bak`.
- [x] T024 **ASK THE USER FIRST (destructive to PostgreSQL).** After approval:
  - Run quickstart step 5: reset PostgreSQL per the README (never `docker compose down -v`), then run `docker compose run --rm --no-deps api python /workspace/scripts/compare_retrieval_strategies.py --strategy passage_hybrid --source-directory /workspace/sample_data/atlas --api-origin http://api:8000`.
  - Confirm that SC-003 holds: top-five retrieval ≥ 1.00 and citation correctness ≥ 1.00.
- [x] T025 Append the T024 run (run_id, date, metrics) to `evaluation/parser_comparison.md` under the Decision section. Mark SC-006 as met or still open, with the measured abstention accuracy and conflict rate.

---

## Dependencies & Execution Order

- **Setup (T001–T002)** comes first. The image must contain pypdfium2 before the preflight (T013) can run. pypdf is removed only in T018, after its code and tests are gone.
- **US1 (T003–T018)** depends on Setup. Within US1:
  - T004 comes before T005.
  - T003–T006 come before T007 (red run).
  - T007 comes before T008–T015.
  - T008 and T009 come before T010.
  - T012–T015 come before T018.
  - T011, T016, and T017 are independent of the backend chain.
- **US2 (T019–T022)**: The writing can start after US1 begins, but the claims must reflect the final US1 behavior. Finish US1 before T022.
- **Polish (T023–T025)** depends on US1 and US2. T024 needs explicit user approval.

## Parallel Examples

```text
US1 tests:     T003 (profile tests) ‖ T004 → T005 (parser unit tests) ‖ T006 (integration test)
US1 impl:      T008 → T009 → T010 (profile, settings, call sites) ‖ T011 (.env.example)
               T012 → T013 → T014 → T015 (backend parser chain)
               T016 (script delete) ‖ T017 (web)
US2:           T019 (README) ‖ T020 (parser_comparison.md) ‖ T021 (AGENTS.md)
```

## Implementation Strategy

1. **MVP = Setup + US1.** After that, pypdf is gone, every PDF runs through Docling, and every error path is covered. It can ship alone.
2. **US2** makes the docs match the new behavior.
3. **Polish** runs the gated reset and benchmark that record SC-003 and SC-006.
4. Outside a `$speckit-loop`: one phase per approval, and commit only after `continue`.
