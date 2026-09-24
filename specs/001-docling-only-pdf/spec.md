# Feature Specification: Docling-Only PDF Parsing

**Feature Branch**: `pdf-improvement`

**Created**: 2026-09-24

**Status**: Draft

**Input**: User description: "We want to remove the pypdf implementation, it should only work with docling. Then update the README, so that it reflects the changes related to docling"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every PDF is parsed by the single supported parser (Priority: P1)

A workspace owner uploads a PDF. The system always extracts it with the layout-aware, OCR-capable parser (Docling). There is no alternative PDF parser to select, configure, or accidentally fall back to. Digital, multi-column, table-heavy, and scanned English PDFs all produce searchable, citable passages with page and region locators.

**Why this priority**: This is the core request. One parser removes a configuration branch, a corpus-profile variant, and a second set of behaviors that must be tested and documented.

**Independent Test**: Start the system with default configuration and upload each representative PDF fixture (digital, multi-column, table-heavy, scanned). Every upload succeeds. Every stored PDF passage carries a region locator, and the corpus profile names only the Docling parser.

**Acceptance Scenarios**:

1. **Given** a fresh system with default configuration, **When** a user uploads a digital multi-page English PDF, **Then** ingestion succeeds and every PDF passage has a page-and-region locator.
2. **Given** a fresh system, **When** a user uploads a scanned English PDF, **Then** ingestion succeeds through OCR instead of being rejected as "no embedded text".
3. **Given** a password-protected, corrupt, or empty PDF, **When** a user uploads it, **Then** the user receives a sanitized, non-retryable parse error with no raw parser internals.
4. **Given** the running system, **When** an operator inspects the active corpus profile, **Then** the PDF parser entry identifies Docling with its version and OCR/layout options, and no other parser option exists.

---

### User Story 2 - README accurately describes Docling PDF support (Priority: P2)

A new contributor or evaluator reads the README. It describes current PDF behavior: layout-aware parsing, local English OCR for scanned PDFs, table and multi-column handling, bundled offline models, and region locators stored but not visually highlighted. It no longer claims that scanned PDFs are rejected or that tables and multi-column layouts are out of scope.

**Why this priority**: Documentation is how users learn the supported formats and limits. It depends on Story 1 being settled.

**Independent Test**: Review the README against the delivered behavior. Every PDF-related statement matches observed behavior. No statement references pypdf as a selectable or default parser.

**Acceptance Scenarios**:

1. **Given** the updated README, **When** a reader checks the supported formats, **Then** scanned English PDFs are listed as supported through local OCR, and encrypted PDFs remain unsupported.
2. **Given** the updated README, **When** a reader checks setup and privacy sections, **Then** the README states that Docling models are bundled at image build time, that no PDF parsing happens over the network, and that the API image is larger because of those models.
3. **Given** the updated README, **When** a reader checks limitations, **Then** it states that PDF region locators are stored and returned but not visually highlighted in this release.

---

### Edge Cases

- A PDF where OCR finds no readable text: user receives a sanitized "no extractable text" parse error.
- A PDF that exceeds the parser timeout: user receives a sanitized, non-retryable timeout error; the ingestion job does not stay `running`.
- Historical page-only locators (benchmark gold locators and existing test data): page-level gold locators still match Docling region passages on the same page.
- The versioned comparison artifact keeps the historical pypdf numbers as an audit record.
- The parser-comparison tooling loses its second parser; it must no longer offer pypdf as a choice.
- Non-PDF formats (Markdown, text, DOCX) are unaffected.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST parse every PDF upload with Docling. No other PDF parser is available at runtime.
- **FR-002**: System MUST remove the pypdf parsing path, its configuration choice, its corpus-profile entry, and its runtime dependency.
- **FR-003**: The corpus profile MUST identify only the Docling parser, including version and OCR/layout options.
- **FR-004**: System MUST keep sanitized, non-retryable error mapping for password-protected, corrupt, empty, OCR-failed, layout-failed, and timed-out PDFs.
- **FR-005**: New PDF passages MUST use page-and-region locators. System MUST keep read-side support for page-only locators so that benchmark gold locators, citation display, and evaluation matching keep working.
- **FR-006**: Parser-comparison tooling and its documentation MUST stop offering pypdf as a runnable option. The historical comparison results MUST stay in the versioned artifact, with a note that pypdf was removed and why.
- **FR-007**: Tests MUST stop covering the pypdf path and MUST cover Docling-only dispatch and the corpus profile contents.
- **FR-008**: The environment template and settings MUST NOT expose a PDF parser choice.
- **FR-009**: README MUST describe Docling PDF support: layout and table handling, multi-column handling, local English OCR for scanned PDFs, bundled offline models, image-size impact, and region locators stored without visual highlighting.
- **FR-010**: README MUST remove statements that are now false: scanned PDFs rejected, "PDFs with embedded text" only, and tables or multi-column layouts out of scope.
- **FR-011**: Project contributor guidance (AGENTS.md) MUST stop describing pypdf as the default parser or a comparison candidate. Rules that still apply MUST remain: offline models, local-only Docling, and sanitized errors.
- **FR-012**: The removal MUST NOT change behavior for Markdown, text, or DOCX ingestion.
- **FR-013**: The comparison artifact and AGENTS.md MUST replace the "parity before default" gate with the forward quality gate in SC-006. They MUST record the current abstention and conflict gap as an open follow-up item, with the measured values and the date.

### Key Entities

- **Corpus profile**: The recorded contract for how the corpus was built. Includes chunking settings, retrieval unit strategy, and PDF parser identity (name, version, OCR mode, layout mode). After this feature, the PDF parser identity is always Docling.
- **PDF passage locator**: Where a passage came from in its source PDF. New passages use page plus normalized bounding region. Page-only locators remain a valid read and match format.
- **Parser comparison record**: The versioned audit artifact of parser benchmark results. It keeps historical pypdf results and records the removal decision.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the four representative PDF fixtures (digital, multi-column, table-heavy, scanned) ingest successfully with default configuration.
- **SC-002**: 0 remaining runtime references to the removed parser in application source, dependencies, environment template, or README, outside historical audit records.
- **SC-003**: After reset and full reingestion, the Atlas benchmark keeps citation correctness at or above 1.00 and top-five retrieval at or above 1.00, which matches the recorded Docling baseline.
- **SC-004**: Every PDF-related claim in the README matches observed behavior in a reviewer walkthrough, with 0 contradictions.
- **SC-005**: Existing Markdown, text, and DOCX ingestion tests pass unchanged.
- **SC-006** *(follow-up gate, non-blocking for this removal)*: On the Atlas benchmark after full reingestion, abstention accuracy is at least 0.90 and the conflict rate is at most 0.05, which matches the former pypdf baseline. Until this gate is met, the gap stays recorded as an open follow-up item.

## Assumptions

- This is a development environment. All ingestion goes through Docling from now on. No handling for stale pypdf corpora or stale parser settings is needed: no fail-fast, no upgrade path, and no schema migration. The development database is reset and reingested once for the benchmark in SC-003; that reset needs explicit operator approval.
- Docling, its bundled layout/table models, and the English OCR engine are already in the API image. This feature adds no new dependency; it removes one.
- Page-only locator support stays on the read side because benchmark gold locators use page-level locators and AGENTS.md defines page-level gold matching against region passages.
- The PDF parser setting is removed entirely; there is nothing to select.
- Visual PDF highlighting remains out of scope; the source viewer stays an extracted-text viewer.
- Encrypted and password-protected PDFs remain unsupported.
- Only the README and AGENTS.md need documentation updates; other historical specs and design notes are not rewritten.
- **Promotion gate**: The removal goes ahead even though the recorded comparison does not meet the AGENTS.md parity gate. Docling is at parity or better on citation validity (1.00 vs 0.9655 correctness) but worse on abstention accuracy (0.85 vs 0.90) and conflict rate (0.10 vs 0.05). The old "parity before default" gate is replaced by a forward quality gate (SC-006), tracked as follow-up work. It does not block this removal.

## Clarifications

### Session 2026-09-24

- Q: Removing pypdf makes Docling the only parser, but Docling misses the parity gate on abstention and conflict rate. How do we proceed? → A: Remove pypdf now. Add a new quality gate: abstention accuracy ≥ 0.90 and conflict rate ≤ 0.05 after reingest. Track the gap as follow-up work, not as a blocker.
- Q: Is stale-corpus and stale-configuration handling (former User Story 2) required? → A: No. This is a development environment, and all ingestion goes through Docling from now on. The story and its requirements were removed; the parser setting is removed entirely.
