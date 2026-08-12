from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from decision_assistant.ingestion.parsers import (
    DocumentParseError,
    _reconstruct_pdf_lines,
    parse_document,
)


TEXT_PDF = Path("tests/fixtures/text.pdf")
SCANNED_EMPTY_PDF = Path("tests/fixtures/scanned-empty.pdf")


def test_pdf_line_reconstruction_joins_wrapped_sentences() -> None:
    wrapped = (
        "Public authentication is active for Q3 and Marco Silva owns the rollout. Status:\n"
        "active.\n"
        "This statement conflicts with the approved July 8 decision memo, which limits access to an\n"
        "employee-only beta and keeps the public rollout postponed.\n"
        "Offline model packaging\n"
        "Decision: Do not bundle Ollama model weights in the application images. Status: active. Dana Wu\n"
        "owns setup documentation.\n"
    )

    reconstructed = _reconstruct_pdf_lines(wrapped)

    assert "owns the rollout. Status: active." in reconstructed
    assert "limits access to an employee-only beta" in reconstructed
    assert "Dana Wu owns setup documentation." in reconstructed
    # A heading (capitalized, short) must not be joined onto the prior line.
    assert "\nOffline model packaging\nDecision:" in reconstructed



def test_pdf_parser_preserves_page_numbers_and_offsets() -> None:
    parsed = parse_document(TEXT_PDF)

    assert [block.text for block in parsed.blocks] == [
        "Authentication was postponed.",
        "PostgreSQL with pgvector was accepted.",
    ]
    assert [block.locator for block in parsed.blocks] == [
        {"kind": "pdf_page", "page": 1},
        {"kind": "pdf_page", "page": 2},
    ]
    assert all(
        parsed.content[block.start_offset : block.end_offset] == block.text
        for block in parsed.blocks
    )


def test_pdf_without_embedded_text_requires_ocr() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(SCANNED_EMPTY_PDF)

    assert error.value.code == "ocr_not_supported"


def test_encrypted_pdf_returns_password_error(tmp_path: Path) -> None:
    encrypted = tmp_path / "encrypted.pdf"
    reader = PdfReader(TEXT_PDF)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt("secret")
    with encrypted.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(DocumentParseError) as error:
        parse_document(encrypted)

    assert error.value.code == "pdf_password_protected"


def test_corrupt_pdf_returns_parser_specific_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a PDF")

    with pytest.raises(DocumentParseError) as error:
        parse_document(corrupt)

    assert error.value.code == "pdf_parse_failed"
