# Data Model: Docling-Only PDF Parsing

No database schema change and no Alembic revision. The only changes are to in-code contracts and to JSON values that are stored or returned.

## Corpus profile (stored on `DocumentVersion`, returned in ingestion summaries and evaluation snapshots)

| Field | Before | After |
|---|---|---|
| chunking fields (`algorithm`, `encoding`, token budgets) | unchanged | unchanged |
| `retrieval_unit_strategy` | unchanged | unchanged |
| `pdf_parser` | `{"name": "pypdf", "version": "5.9.0", "ocr": "disabled", "layout": "text-order-v1"}` by default, or the Docling entry when selected | Always `{"name": "docling", "version": "2.130.0", "ocr": "tesseract-eng", "layout": "docling-layout-v1"}` |

**Validation**: `resolve_corpus_profile(preset, retrieval_unit_strategy)` takes no parser argument. Unknown presets and strategies still raise `ValueError`.

**State**: A corpus built under the pypdf profile no longer matches `CURRENT_CHUNKING_PROFILE`. The existing generic guard applies. This feature adds no extra handling.

## PDF passage locator (stored on passages, returned by citations)

| Kind | Written by new ingestion | Accepted on read/match |
|---|---|---|
| `pdf_region` `{kind, page, bbox[4] normalized 0–1, top-left origin}` | yes | yes |
| `pdf_page` `{kind, page}` | **no** | yes: gold locators, citation labels, evaluation page matching |

## Ingestion error codes (document `error.code`, all `retryable: false`, HTTP 422 on parse)

| Code | Trigger | Status |
|---|---|---|
| `pdf_password_protected` | PDFium preflight reports an incorrect password | kept; detection moves from pypdf to the PDFium preflight |
| `pdf_parse_failed` | Preflight or Docling fails to load the file, or an unclassified conversion failure | kept |
| `pdf_ocr_failed` | Docling error mentions OCR | kept |
| `pdf_layout_failed` | Docling error mentions layout or pipeline | kept |
| `pdf_parse_timeout` | Conversion exceeds `model_timeout_seconds` | kept; now applies to every PDF and only to PDFs |
| `pdf_no_extractable_text` | Conversion succeeds with zero text blocks | **new** |
| `ocr_not_supported` | (pypdf) no embedded text | **removed** |

## Settings

| Setting | Before | After |
|---|---|---|
| `pdf_parser` / `PDF_PARSER` | `"pypdf"` default, validated against two profiles | **removed**. A leftover env var is ignored (`extra="ignore"`). |
