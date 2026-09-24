# Contract: PDF Ingestion (Docling-only)

Scope: the externally visible behavior of `POST` document upload and ingestion status for `.pdf` sources. Request and response shapes do not change. Only values change.

## Parse outcome

| Input | Outcome |
|---|---|
| Digital, multi-column, or table-heavy English PDF | `status: completed`. Every PDF passage locator is `pdf_region`. |
| Scanned English PDF with readable text | `status: completed` through local English OCR. Every locator is `pdf_region`. |
| Blank or unreadable scanned PDF | `status: failed`, `error: {code: "pdf_no_extractable_text", retryable: false}` |
| PDF with a user password | `status: failed`, `error: {code: "pdf_password_protected", retryable: false}` |
| Owner-password-only PDF (opens without a password) | Parsed like any other PDF |
| Corrupt bytes | `status: failed`, `error: {code: "pdf_parse_failed", retryable: false}` |
| OCR or layout engine failure | `pdf_ocr_failed` or `pdf_layout_failed`, `retryable: false` |
| Conversion exceeds the timeout | `pdf_parse_timeout`, `retryable: false`. The job does not stay `running`. |

Error `message` values are fixed, sanitized strings. Raw Docling or PDFium exception text never reaches API consumers.

## Corpus profile in responses

The `chunking_profile.pdf_parser` field in ingestion summaries and in the evaluation `corpus_snapshot` always equals:

```json
{"name": "docling", "version": "2.130.0", "ocr": "tesseract-eng", "layout": "docling-layout-v1"}
```

## Web display contract (`IngestionStatus`)

| Code | Message shown |
|---|---|
| `pdf_no_extractable_text` | "This PDF contains no readable text." |
| `pdf_password_protected` | unchanged |
| `pdf_parse_failed` | unchanged |
| `ocr_not_supported` | removed |

Other codes fall back to the sanitized API `message`, as they do today.

## Non-PDF sources

The `.md`, `.txt`, and `.docx` parse paths, locators, and error codes do not change. They do not run through the PDF worker thread or timeout.
