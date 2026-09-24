from pathlib import Path

import pytest

from decision_assistant.ingestion.parsers import DocumentParseError, parse_document


FIXTURE_DIRECTORY = Path("tests/fixtures/pdf")


@pytest.mark.parametrize(
    "fixture_name",
    [
        "digital-english.pdf",
        "multi-column-english.pdf",
        "table-heavy-english.pdf",
        "scanned-english.pdf",
    ],
)
def test_docling_ingests_representative_english_fixtures(
    fixture_name: str,
) -> None:
    parsed = parse_document(FIXTURE_DIRECTORY / fixture_name)

    assert parsed.content.strip()
    assert parsed.blocks
    assert all(block.locator["kind"] == "pdf_region" for block in parsed.blocks)
    assert all(
        parsed.content[block.start_offset : block.end_offset] == block.text
        for block in parsed.blocks
    )


def test_docling_reports_scanned_empty_pdf_without_text() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(Path("tests/fixtures/scanned-empty.pdf"))

    assert error.value.code == "pdf_no_extractable_text"
