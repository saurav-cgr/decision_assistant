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


def test_markdown_headings_carry_level_boundary_and_group_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "headings.md"
    source.write_text(
        "# Architecture\n\n"
        "Text A\n\n"
        "## Storage\n\n"
        "Text B\n\n"
        "## Storage\n\n"
        "Text C\n"
    )

    parsed = parse_document(source)

    headings = [block for block in parsed.blocks if block.block_type == "heading"]
    assert [block.attributes["level"] for block in headings] == [1, 2, 2]
    assert [block.boundary_before for block in headings] == ["none", "hard", "hard"]
    assert headings[0].group_path == ("heading-1:architecture#1",)
    assert headings[1].group_path == (
        "heading-1:architecture#1",
        "heading-2:storage#1",
    )
    # Duplicate heading text gets a stable occurrence suffix.
    assert headings[2].group_path == (
        "heading-1:architecture#1",
        "heading-2:storage#2",
    )
    paragraphs = [block for block in parsed.blocks if block.block_type == "paragraph"]
    assert all(block.boundary_before == "soft" for block in paragraphs)
    assert paragraphs[0].group_path == ("heading-1:architecture#1",)
    assert paragraphs[2].group_path == (
        "heading-1:architecture#1",
        "heading-2:storage#2",
    )


def test_markdown_setext_heading_is_leveled(tmp_path: Path) -> None:
    source = tmp_path / "setext.md"
    source.write_text("Architecture\n===========\n\nBody text\n")

    parsed = parse_document(source)

    heading = parsed.blocks[0]
    assert heading.block_type == "heading"
    assert heading.text == "Architecture"
    assert heading.attributes["level"] == 1
    assert heading.boundary_before == "none"
    assert heading.locator == {"kind": "lines", "start": 1, "end": 2}


def test_txt_paragraphs_use_soft_boundaries_without_headings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "plain.txt"
    source.write_text("First paragraph\ncontinues\n\nSecond paragraph\n")

    parsed = parse_document(source)

    assert [block.block_type for block in parsed.blocks] == [
        "paragraph",
        "paragraph",
    ]
    assert [block.boundary_before for block in parsed.blocks] == ["none", "soft"]
    assert all(block.group_path == () for block in parsed.blocks)
    assert all(block.attributes == {} for block in parsed.blocks)
