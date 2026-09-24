# Implementation Plan: Docling-Only PDF Parsing

**Branch**: `pdf-improvement` (speckit feature id `001-docling-only-pdf`) | **Date**: 2026-09-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-docling-only-pdf/spec.md`

## Summary

Remove the pypdf parser so that every PDF goes through the local, offline Docling pipeline. Collapse the two-entry parser profile table into one Docling profile, and drop the `pdf_parser` setting and its call sites. Replace the two error behaviors that pypdf provided:
- **Password detection**: a PDFium preflight replaces the pypdf check. pypdfium2 is already installed with Docling.
- **Empty-document signal**: the new `pdf_no_extractable_text` code replaces `ocr_not_supported`.

Update the README, AGENTS.md, and the parser comparison record to describe Docling-only behavior and the forward quality gate (SC-006).

## Technical Context

**Language/Version**: Python 3.12 (API) and TypeScript with React/Vite (web)

**Primary Dependencies**: FastAPI, pydantic-settings, Docling 2.130.0 with Tesseract (eng), and pypdfium2 5.13.0 (already present transitively; to be declared). pypdf 5.9.0 is removed.

**Storage**: PostgreSQL with pgvector. No schema change.

**Testing**: pytest and pytest-asyncio (`make test-api`); Vitest and Testing Library (`make test-web`)

**Target Platform**: Linux containers through Docker Compose

**Project Type**: Web service (FastAPI monolith) plus a web SPA

**Performance Goals**: No regression in Atlas ingest time against the recorded Docling baseline (41.4 s for 6 documents)

**Constraints**:
- No runtime model downloads.
- Docling stays local-only with English OCR.
- Error messages are sanitized.
- Hand-written files stay under 500 lines.
- The frozen `parse_document`, `ParsedDocument`, `_SourceBlock`, and chunker signatures do not change.

**Scale/Scope**: About 12 source files, 5 test files, 1 script deletion, and 3 docs

## Constitution Check

`.specify/memory/constitution.md` is an unfilled template, so the gates come from `AGENTS.md` critical constraints.

| Gate | Status | Notes |
|---|---|---|
| Secrets never committed | PASS | No secret files touched. `.env.gemini.bak` stays unstaged. |
| Corpus contract: no in-place migration | PASS | Profile change leads to reset and reingest (R8). |
| Schema migrations: never edit 0001 | PASS | No migration needed. |
| Reset safety: PostgreSQL only, ask first | PASS | Quickstart step 5 is gated on approval. |
| SQL: no interpolation | PASS | No SQL touched. |
| Escalation: new dependency needs approval | PASS (approved 2026-09-24) | The user approved declaring `pypdfium2==5.13.0` as a direct dependency (R2). It is already installed, so the image does not grow. |
| Escalation: destructive reset needs approval | **NEEDS APPROVAL (at execution)** | One reset for SC-003 validation. |
| File size < 500 lines | PASS | `parsers.py` shrinks from 496 to about 440 lines. The preflight goes in `docling_parser.py` (136 lines). |
| Layering | PASS | Error classification stays in backend Python. The web change is a display-string map only. |
| Frozen Docling contract (parse signatures, dispatch only inside `_parse_pdf_document`) | PASS | Dispatch stays inside `_parse_pdf_document`. The preflight runs inside the Docling path. |

**Post-design re-check**: No new violations. Only the reset approval remains, and it is needed at execution time (step 6).

## Project Structure

### Documentation (this feature)

```text
specs/001-docling-only-pdf/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/ingestion-pdf.md
├── checklists/requirements.md
└── tasks.md             # next: /speckit-tasks
```

### Source Code (touched paths)

```text
api/
  pyproject.toml                          - pypdf, + pypdfium2==5.13.0
  src/decision_assistant/
    config.py                             - pdf_parser field + validator
    main.py                               - pdf_parser arg
    ingestion/
      profiles.py                         PDF_PARSER_PROFILES -> PDF_PARSER_PROFILE; drop param
      parsers.py                          - pypdf import, _parse_pypdf_document, _reconstruct_pdf_lines
      docling_parser.py                   + PDFium preflight; zero blocks -> pdf_no_extractable_text
      service.py                          worker thread + timeout for .pdf only
    retrieval/router.py                   - pdf_parser arg
    answering/router.py                   - pdf_parser arg
    evaluation/router.py                  - pdf_parser arg
    documents/router.py                   - pdf_parser arg
  tests/
    unit/test_pdf_parser.py               remove pypdf tests; rewrite encrypted/empty; non-PDF sync path
    unit/test_chunking_profiles.py        Docling-only profile; no pdf_parser setting
    integration/test_docling_pdf_ingestion.py  drop monkeypatch; + blank PDF case
web/src/
  components/IngestionStatus.tsx          ocr_not_supported -> pdf_no_extractable_text
  pages/Workspace.test.tsx                update code
scripts/compare_pdf_parsers.py            delete
.env.example                              - PDF_PARSER
README.md                                 Docling PDF behavior
AGENTS.md                                 Docling-only rules; forward gate
evaluation/parser_comparison.md           decision + follow-up; drop pypdf repro
```

**Structure Decision**: Existing layout (`api/`, `web/`, `scripts/`). No new modules.

## Implementation Steps

The steps are ordered for the one-step-at-a-time approval gate. Each step leaves the tests green.

1. **Profile and settings collapse**: Update `profiles.py`, `config.py`, `main.py`, the 4 routers, `.env.example`, and `test_chunking_profiles.py`. Verify with `make test-api`.
2. **Parser removal and new error mapping**: Remove the pypdf code in `parsers.py`. Add the preflight and `pdf_no_extractable_text` in `docling_parser.py`. Scope the timeout to `.pdf` in `service.py`. Rewrite `test_pdf_parser.py` and the integration test. Swap the dependency in `pyproject.toml` and rebuild the image. Verify with `make test-api` and quickstart steps 2 and 4.
3. **Web error message**: Update `IngestionStatus.tsx` and `Workspace.test.tsx`. Verify with `make test-web` and `npm run build`.
4. **Tooling and records**: Delete `compare_pdf_parsers.py`. Update `parser_comparison.md` with the decision, the follow-up, and the removed pypdf reproduction.
5. **Docs**: Update the README and AGENTS.md. Verify with the quickstart step 1 sweep and step 6 walkthrough.
6. **Validation run (needs reset approval)**: Run quickstart step 5. Record the SC-003 and SC-006 numbers in `parser_comparison.md`.

## Risks

- **Real Docling in unit tests is slow**: Unit tests stub the conversion. Only the integration test runs real Docling, and it already does today.
- **Owner-password-only PDFs are now accepted**: This is intentional (R2). It is documented in the contract.
- **SC-006 gap stays open**: Tracked as a follow-up and non-blocking, as the user decided on 2026-09-24.

## Complexity Tracking

No violations requiring justification.
