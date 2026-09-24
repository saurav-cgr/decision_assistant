from pathlib import Path
from types import SimpleNamespace

import pytest

from decision_assistant import config
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
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
) -> None:
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(pdf_parser="docling"),
    )

    try:
        parsed = parse_document(FIXTURE_DIRECTORY / fixture_name)
    except DocumentParseError as error:
        assert error.code != "ocr_not_supported"
        raise

    assert parsed.content.strip()
    assert parsed.blocks
    assert all(block.locator["kind"] == "pdf_region" for block in parsed.blocks)
    assert all(
        parsed.content[block.start_offset : block.end_offset] == block.text
        for block in parsed.blocks
    )
