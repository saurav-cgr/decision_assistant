from pathlib import Path

from decision_assistant.ingestion.parsers import parse_document

FIXTURE = Path("tests/fixtures/meeting.md")


def test_markdown_parser_preserves_line_locator() -> None:
    parsed = parse_document(FIXTURE)

    assert parsed.blocks[0].locator == {"kind": "lines", "start": 1, "end": 2}
    assert parsed.blocks[0].text.startswith("Architecture Sync")


def test_text_parser_normalizes_line_endings_and_preserves_lines(
    tmp_path: Path,
) -> None:
    source = tmp_path / "notes.txt"
    source.write_bytes(b"First decision  \r\ncontinues here\r\n\r\nSecond decision\r\n")

    parsed = parse_document(source)

    assert [block.text for block in parsed.blocks] == [
        "First decision\ncontinues here",
        "Second decision",
    ]
    assert [block.locator for block in parsed.blocks] == [
        {"kind": "lines", "start": 1, "end": 2},
        {"kind": "lines", "start": 4, "end": 4},
    ]
