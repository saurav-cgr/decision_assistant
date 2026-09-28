"""Pre-parse validation of an upload's actual content (T063/T064, US8; FR-020/FR-021).

The extension and the declared media type are checked at upload time (`documents/service.py`); this
is the other half — the bytes themselves. It runs immediately before `parse_document`, so a file whose
content contradicts its extension, or a PDF longer than the configured limit, is rejected with a
sanitized non-retryable error instead of being fed to Docling (slow, and for a mislabelled file the
backend error is confusing rather than actionable).

Two deliberate limits: the page count is only checked for PDFs (that is what `max_pdf_pages` names),
and a PDF whose page count cannot be read is *not* rejected here — Docling still fails it with its own
sanitized parse error, and rejecting on a counting failure would turn a library problem into a
permanent "invalid file" verdict for the user.
"""

from __future__ import annotations

import codecs
from pathlib import Path

import pypdfium2 as pdfium

from decision_assistant.ingestion.parsers import DocumentParseError

PDF_SUFFIX = ".pdf"
DOCX_SUFFIX = ".docx"
TEXT_SUFFIXES = {".md", ".txt"}

#: Bytes a file must start with to be the format its extension claims. `.md`/`.txt` are handled
#: separately: text has no magic number, so the probe is "decodes as UTF-8 and contains no NUL".
_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    PDF_SUFFIX: (b"%PDF-",),
    DOCX_SUFFIX: (b"PK\x03\x04",),
}

_PROBE_BYTES = 8192


def _probe_bytes_match(path: Path) -> bool:
    suffix = path.suffix.lower()
    with path.open("rb") as handle:
        # One byte past the probe, so `complete` can tell "the file ended inside the probe" from
        # "there is more file behind it" without a second stat/read.
        head = handle.read(_PROBE_BYTES + 1)

    expected = _MAGIC_BYTES.get(suffix)
    if expected is not None:
        return any(head.startswith(magic) for magic in expected)
    if suffix in TEXT_SUFFIXES:
        if b"\x00" in head:
            return False
        # Incremental decode: a multi-byte character straddling the probe boundary is *not* a
        # reason to reject a valid file (DB55, checker V136 — an 8191-byte ASCII prefix followed by
        # an em dash was refused permanently). `final=True` only when the probe held the whole file,
        # so a genuinely truncated trailing character in a short file is still caught.
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            decoder.decode(head[:_PROBE_BYTES], final=len(head) <= _PROBE_BYTES)
        except UnicodeDecodeError:
            return False
        return True
    # An unknown suffix is `parse_document`'s problem, not this module's.
    return True


def _pdf_page_count(path: Path) -> int | None:
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception:
        return None
    try:
        return len(document)
    finally:
        document.close()


def validate_document_content(path: Path, *, max_pdf_pages: int) -> None:
    """Reject content contradicting its extension, or a PDF over the configured page limit."""
    if not _probe_bytes_match(path):
        raise DocumentParseError(
            "content_type_mismatch",
            f"File content does not match its {path.suffix.lower() or '<none>'} extension",
        )
    if path.suffix.lower() != PDF_SUFFIX:
        return
    pages = _pdf_page_count(path)
    if pages is not None and pages > max_pdf_pages:
        raise DocumentParseError(
            "pdf_page_limit_exceeded",
            f"PDF has {pages} pages, which exceeds the configured limit of "
            f"{max_pdf_pages} pages",
        )
