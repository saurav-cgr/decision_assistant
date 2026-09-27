"""T061 (US8/FR-020/FR-021): reject an upload whose bytes contradict it, before the parser runs.

Three separate limits are covered here because they are enforced at different layers and a
regression in any of them is invisible from the others: the extension/declared-media-type check at
upload time (`documents/service.py`, exercised by the upload API tests), the content-level magic-byte
and page-count checks in `ingestion/validation.py`, and the byte-size cap in `documents/storage.py`.
"""

import io
from pathlib import Path

import pytest
from fastapi import UploadFile
from reportlab.pdfgen import canvas

from decision_assistant.documents.storage import LocalFileStorage, StoredObjectTooLarge
from decision_assistant.ingestion.parsers import DocumentParseError
from decision_assistant.ingestion.service import _parse_for_ingestion
from decision_assistant.ingestion.validation import validate_document_content

_LIMIT = 2


def _write_pdf(path: Path, pages: int) -> Path:
    document = canvas.Canvas(str(path))
    for index in range(pages):
        document.drawString(72, 720, f"page {index + 1}")
        document.showPage()
    document.save()
    return path


def test_declared_pdf_without_the_pdf_magic_bytes_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "document.pdf"
    path.write_text("This is prose, not a PDF.")

    with pytest.raises(DocumentParseError) as excinfo:
        validate_document_content(path, max_pdf_pages=_LIMIT)

    assert excinfo.value.code == "content_type_mismatch"
    # Sanitized: the message names the extension, never the file's path or content.
    assert ".pdf" in excinfo.value.message
    assert str(tmp_path) not in excinfo.value.message


def test_declared_docx_without_the_zip_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "document.docx"
    path.write_bytes(b"not a zip container at all")

    with pytest.raises(DocumentParseError) as excinfo:
        validate_document_content(path, max_pdf_pages=_LIMIT)

    assert excinfo.value.code == "content_type_mismatch"


def test_binary_content_declared_as_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(b"# Heading\n\x00\x01\x02 binary tail\n")

    with pytest.raises(DocumentParseError) as excinfo:
        validate_document_content(path, max_pdf_pages=_LIMIT)

    assert excinfo.value.code == "content_type_mismatch"


def test_matching_content_passes_validation(tmp_path: Path) -> None:
    markdown = tmp_path / "notes.md"
    markdown.write_text("# Heading\n\nSome prose.\n")
    pdf = _write_pdf(tmp_path / "small.pdf", pages=_LIMIT)

    # No exception: the happy path must stay quiet, or every upload would fail loudly.
    validate_document_content(markdown, max_pdf_pages=_LIMIT)
    validate_document_content(pdf, max_pdf_pages=_LIMIT)


async def test_multibyte_character_straddling_the_probe_boundary_is_accepted(
    tmp_path: Path,
) -> None:
    # DB55 (checker V136): the probe is 8192 bytes, and an em dash placed so that it starts at byte
    # 8191 puts bytes 8192-8193 outside a naive strict decode — a valid file that was refused
    # permanently. Real prose hits this with em dashes, smart quotes, accents and CJK text.
    for suffix in (".md", ".txt"):
        path = tmp_path / f"boundary{suffix}"
        path.write_bytes(b"a" * 8191 + "—".encode() + b" tail\n")

        validate_document_content(path, max_pdf_pages=_LIMIT)


async def test_truncated_multibyte_tail_in_a_short_file_is_still_rejected(
    tmp_path: Path,
) -> None:
    # The other half of the same fix: relaxing the boundary must not disable the check. A file that
    # fits inside the probe and ends mid-character is genuinely invalid UTF-8.
    path = tmp_path / "truncated.md"
    path.write_bytes(b"# Heading\n" + b"text \xe2\x80")

    with pytest.raises(DocumentParseError) as excinfo:
        validate_document_content(path, max_pdf_pages=_LIMIT)

    assert excinfo.value.code == "content_type_mismatch"


def test_pdf_over_the_page_limit_is_rejected_with_the_limit_named(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "long.pdf", pages=_LIMIT + 1)

    with pytest.raises(DocumentParseError) as excinfo:
        validate_document_content(path, max_pdf_pages=_LIMIT)

    assert excinfo.value.code == "pdf_page_limit_exceeded"
    # FR-021 requires the error to name the configured limit, not just report a failure.
    assert str(_LIMIT) in excinfo.value.message
    assert str(_LIMIT + 1) in excinfo.value.message


def test_unreadable_pdf_is_left_to_the_parser(tmp_path: Path) -> None:
    # A `%PDF-` header that pdfium cannot open is a parse failure, not an invalid-file verdict: the
    # validator has no opinion, so the user still gets Docling's sanitized parse error instead of a
    # permanent "this file is wrong" verdict caused by a library limitation.
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nthis body is not a real PDF\n")

    validate_document_content(path, max_pdf_pages=_LIMIT)


async def test_content_validation_runs_before_the_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "document.pdf"
    path.write_text("not a pdf at all")
    parser_called = False

    def _fail_if_called(_path: Path) -> object:
        nonlocal parser_called
        parser_called = True
        raise AssertionError("the parser must not be reached for a mismatched file")

    monkeypatch.setattr(
        "decision_assistant.ingestion.service.parse_document", _fail_if_called
    )

    with pytest.raises(DocumentParseError) as excinfo:
        await _parse_for_ingestion(path)

    assert excinfo.value.code == "content_type_mismatch"
    assert parser_called is False


async def test_oversized_upload_is_still_rejected_by_the_size_check(
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path)
    upload = UploadFile(filename="large.md", file=io.BytesIO(b"x" * 100))

    with pytest.raises(StoredObjectTooLarge):
        await storage.put_upload(key="large.md", upload=upload, max_bytes=10)

    # The partial file is cleaned up, so a rejected upload cannot be picked up later.
    assert not (tmp_path / "large.md").exists()
