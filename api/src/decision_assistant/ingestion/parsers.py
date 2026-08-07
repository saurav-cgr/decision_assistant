from dataclasses import dataclass
from pathlib import Path

LineLocator = dict[str, str | int]
SUPPORTED_TEXT_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    text: str
    locator: LineLocator
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_path: Path
    content: str
    blocks: tuple[ParsedBlock, ...]


def parse_document(path: Path) -> ParsedDocument:
    """Parse a Markdown or text file while retaining stable source line ranges."""
    if path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
        raise ValueError(f"Unsupported text document type: {path.suffix or '<none>'}")

    source = path.read_text(encoding="utf-8")
    normalized_lines = [line.rstrip() for line in source.splitlines()]
    source_blocks = _collect_blocks(normalized_lines)

    content_parts: list[str] = []
    blocks: list[ParsedBlock] = []
    offset = 0
    for start_line, end_line, text in source_blocks:
        if content_parts:
            content_parts.append("\n\n")
            offset += 2

        start_offset = offset
        content_parts.append(text)
        offset += len(text)
        blocks.append(
            ParsedBlock(
                text=text,
                locator={"kind": "lines", "start": start_line, "end": end_line},
                start_offset=start_offset,
                end_offset=offset,
            )
        )

    return ParsedDocument(
        source_path=path,
        content="".join(content_parts),
        blocks=tuple(blocks),
    )


def _collect_blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    block_lines: list[str] = []
    start_line = 0

    for line_number, line in enumerate(lines, start=1):
        if line.strip():
            if not block_lines:
                start_line = line_number
            block_lines.append(line)
            continue

        if block_lines:
            blocks.append((start_line, line_number - 1, "\n".join(block_lines)))
            block_lines = []

    if block_lines:
        blocks.append((start_line, len(lines), "\n".join(block_lines)))

    return blocks
