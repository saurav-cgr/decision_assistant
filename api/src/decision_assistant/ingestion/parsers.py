from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile

from docx import Document as open_docx
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from decision_assistant.errors import ApplicationError

Boundary = Literal["hard", "soft", "none"]
AttributeValue = str | int | float | bool | None
SourceLocator = dict[str, str | int | float | bool | list[str] | None]
SUPPORTED_TEXT_SUFFIXES = {".md", ".txt"}
PDF_SUFFIX = ".pdf"
DOCX_SUFFIX = ".docx"


class DocumentParseError(ApplicationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=422,
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    """A source-neutral normalized block.

    ``group_path`` is an ordered tuple of namespaced stable keys from broad to
    narrow (e.g. ``("heading-1:architecture#1", "heading-2:storage#1")`` or
    ``("channel:C123", "thread:171234")``). ``boundary_before`` records whether
    this block may combine with the preceding block.
    """

    text: str
    block_type: str
    group_path: tuple[str, ...]
    boundary_before: Boundary
    attributes: dict[str, AttributeValue]
    locator: SourceLocator
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_path: Path
    content: str
    blocks: tuple[ParsedBlock, ...]


@dataclass(frozen=True, slots=True)
class _SourceBlock:
    text: str
    block_type: str
    group_path: tuple[str, ...]
    boundary_before: Boundary
    attributes: dict[str, AttributeValue]
    locator: SourceLocator


def parse_document(path: Path) -> ParsedDocument:
    """Parse a supported document while retaining stable source locators."""
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return _parse_text_document(path)
    if suffix == PDF_SUFFIX:
        return _parse_pdf_document(path)
    if suffix == DOCX_SUFFIX:
        return _parse_docx_document(path)
    raise ValueError(f"Unsupported document type: {path.suffix or '<none>'}")


def _parse_text_document(path: Path) -> ParsedDocument:
    source = path.read_text(encoding="utf-8")
    normalized_lines = [line.rstrip() for line in source.splitlines()]
    infer_headings = path.suffix.lower() == ".md"
    source_blocks = _collect_text_blocks(normalized_lines, infer_headings)
    return _assemble_document(path, source_blocks)


def _parse_pdf_document(path: Path) -> ParsedDocument:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise DocumentParseError(
                "pdf_password_protected",
                "Password-protected PDF files are not supported",
            )
        source_blocks: list[_SourceBlock] = []
        first = True
        for page_number, page in enumerate(reader.pages, start=1):
            text = _normalize_extracted_text(
                _reconstruct_pdf_lines(page.extract_text() or "")
            )
            if not text:
                continue
            source_blocks.append(
                _SourceBlock(
                    text=text,
                    block_type="page",
                    group_path=(),
                    boundary_before="none" if first else "hard",
                    attributes={},
                    locator={"kind": "pdf_page", "page": page_number},
                )
            )
            first = False
    except DocumentParseError:
        raise
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        raise DocumentParseError(
            "pdf_parse_failed",
            "PDF could not be parsed",
        ) from exc

    if not source_blocks:
        raise DocumentParseError(
            "ocr_not_supported",
            "PDF contains no embedded text; OCR is not supported",
        )
    return _assemble_document(path, source_blocks)


def _parse_docx_document(path: Path) -> ParsedDocument:
    source_blocks: list[_SourceBlock] = []
    heading_stack: list[tuple[int, str]] = []
    heading_counts: dict[tuple[int, str], int] = {}
    paragraph_number = 0
    first = True

    def append_block(
        paragraph: Paragraph,
        *,
        in_table: bool,
    ) -> None:
        nonlocal paragraph_number, first
        paragraph_number += 1
        normalized = _normalize_extracted_text(paragraph.text)
        if not normalized:
            return
        level = _docx_heading_level(paragraph)
        locator = {
            "kind": "docx_paragraphs",
            "start": paragraph_number,
            "end": paragraph_number,
        }
        if level is not None:
            key = _heading_key(level, normalized, heading_counts)
            heading_stack[:] = [
                entry for entry in heading_stack if entry[0] < level
            ]
            heading_stack.append((level, key))
            source_blocks.append(
                _SourceBlock(
                    text=normalized,
                    block_type="heading",
                    group_path=tuple(key for _, key in heading_stack),
                    boundary_before="none" if first else "hard",
                    attributes={"level": level},
                    locator=locator,
                )
            )
        elif in_table:
            source_blocks.append(
                _SourceBlock(
                    text=normalized,
                    block_type="table_cell",
                    group_path=tuple(key for _, key in heading_stack),
                    boundary_before="none" if first else "soft",
                    attributes={},
                    locator=locator,
                )
            )
        else:
            source_blocks.append(
                _SourceBlock(
                    text=normalized,
                    block_type="paragraph",
                    group_path=tuple(key for _, key in heading_stack),
                    boundary_before="none" if first else "soft",
                    attributes={},
                    locator=locator,
                )
            )
        first = False

    try:
        document = open_docx(path)
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                append_block(item, in_table=False)
                continue
            if isinstance(item, Table):
                for row in item.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            append_block(paragraph, in_table=True)
    except (BadZipFile, KeyError, OSError, PackageNotFoundError, ValueError) as exc:
        raise DocumentParseError(
            "docx_parse_failed",
            "DOCX could not be parsed",
        ) from exc

    return _assemble_document(path, source_blocks)


def _docx_heading_level(paragraph: Paragraph) -> int | None:
    name = getattr(paragraph.style, "name", None) or ""
    stripped = name.strip()
    if stripped.startswith("Heading "):
        suffix = stripped[len("Heading ") :].strip()
        if suffix.isdigit() and 1 <= int(suffix) <= 6:
            return int(suffix)
    return None


def _assemble_document(
    path: Path,
    source_blocks: list[_SourceBlock],
) -> ParsedDocument:
    content_parts: list[str] = []
    blocks: list[ParsedBlock] = []
    offset = 0
    for block in source_blocks:
        if content_parts:
            content_parts.append("\n\n")
            offset += 2
        start_offset = offset
        content_parts.append(block.text)
        offset += len(block.text)
        blocks.append(
            ParsedBlock(
                text=block.text,
                block_type=block.block_type,
                group_path=block.group_path,
                boundary_before=block.boundary_before,
                attributes=block.attributes,
                locator=block.locator,
                start_offset=start_offset,
                end_offset=offset,
            )
        )
    return ParsedDocument(
        source_path=path,
        content="".join(content_parts),
        blocks=tuple(blocks),
    )


def _collect_text_blocks(
    lines: list[str],
    infer_headings: bool,
) -> list[_SourceBlock]:
    if infer_headings:
        return _collect_markdown_blocks(lines)
    return _collect_paragraph_blocks(lines)


def _collect_paragraph_blocks(lines: list[str]) -> list[_SourceBlock]:
    blocks: list[_SourceBlock] = []
    current: list[str] = []
    start_line = 0
    first = True
    for line_number, line in enumerate(lines, start=1):
        if line.strip():
            if not current:
                start_line = line_number
            current.append(line)
            continue
        if current:
            blocks.append(
                _SourceBlock(
                    text="\n".join(current),
                    block_type="paragraph",
                    group_path=(),
                    boundary_before="none" if first else "soft",
                    attributes={},
                    locator={"kind": "lines", "start": start_line, "end": line_number - 1},
                )
            )
            first = False
            current = []
    if current:
        blocks.append(
            _SourceBlock(
                text="\n".join(current),
                block_type="paragraph",
                group_path=(),
                boundary_before="none" if first else "soft",
                attributes={},
                locator={"kind": "lines", "start": start_line, "end": len(lines)},
            )
        )
    return blocks


def _collect_markdown_blocks(lines: list[str]) -> list[_SourceBlock]:
    blocks: list[_SourceBlock] = []
    heading_stack: list[tuple[int, str]] = []
    heading_counts: dict[tuple[int, str], int] = {}
    current: list[str] = []
    start_line = 0
    first = True

    def flush_paragraph(end_line: int) -> None:
        nonlocal current, first
        if not current:
            return
        blocks.append(
            _SourceBlock(
                text="\n".join(current),
                block_type="paragraph",
                group_path=tuple(key for _, key in heading_stack),
                boundary_before="none" if first else "soft",
                attributes={},
                locator={"kind": "lines", "start": start_line, "end": end_line},
            )
        )
        first = False
        current = []

    def emit_heading(
        level: int,
        text: str,
        start: int,
        end: int,
    ) -> None:
        nonlocal first
        key = _heading_key(level, text, heading_counts)
        heading_stack[:] = [entry for entry in heading_stack if entry[0] < level]
        heading_stack.append((level, key))
        blocks.append(
            _SourceBlock(
                text=text,
                block_type="heading",
                group_path=tuple(key for _, key in heading_stack),
                boundary_before="none" if first else "hard",
                attributes={"level": level},
                locator={"kind": "lines", "start": start, "end": end},
            )
        )
        first = False

    line_number = 0
    # YAML front matter is not a heading, and its closing "---" must not be
    # interpreted as a Setext underline for the preceding line.
    if lines and lines[0].strip() == "---":
        closing = next(
            (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
            None,
        )
        if closing is not None:
            blocks.append(
                _SourceBlock(
                    text="\n".join(lines[0 : closing + 1]),
                    block_type="paragraph",
                    group_path=(),
                    boundary_before="none" if first else "soft",
                    attributes={},
                    locator={"kind": "lines", "start": 1, "end": closing + 1},
                )
            )
            first = False
            line_number = closing + 1

    while line_number < len(lines):
        line = lines[line_number]
        atx = _atx_heading(line)
        if atx is not None:
            flush_paragraph(line_number)
            level, text = atx
            emit_heading(level, text, line_number + 1, line_number + 1)
            line_number += 1
            continue

        underline = (
            lines[line_number + 1].strip()
            if line_number + 1 < len(lines)
            else ""
        )
        if line.strip() and underline and set(underline) <= {"=", "-"}:
            flush_paragraph(line_number)
            level = 1 if "=" in underline else 2
            emit_heading(level, line.strip(), line_number + 1, line_number + 2)
            line_number += 2
            continue

        if line.strip():
            if not current:
                start_line = line_number + 1
            current.append(line)
        else:
            flush_paragraph(line_number)
        line_number += 1

    flush_paragraph(len(lines))
    return blocks


def _atx_heading(line: str) -> tuple[int, str] | None:
    level = 0
    for char in line:
        if char == "#":
            level += 1
        else:
            break
    if not 1 <= level <= 6:
        return None
    rest = line[level:].strip()
    if not rest:
        return None
    return level, rest


def _slugify(text: str) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in text.lower())
    parts = [part for part in slug.split("-") if part]
    return "-".join(parts) or "section"


def _heading_key(
    level: int,
    text: str,
    counts: dict[tuple[int, str], int],
) -> str:
    slug = _slugify(text)
    counts[(level, slug)] = counts.get((level, slug), 0) + 1
    return f"heading-{level}:{slug}#{counts[(level, slug)]}"


def _normalize_extracted_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _reconstruct_pdf_lines(text: str) -> str:
    """Rejoin PDF line-wraps so sentences are not broken by hard newlines.

    PDF text extraction inserts a newline wherever a line wraps. A wrapped
    continuation almost always starts with a lowercase letter, while a new
    heading, label, or sentence starts with a capital. Join a line onto the
    previous one when the next line begins lowercase. Blank lines are kept as
    paragraph separators.
    """
    joined: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if joined and joined[-1].strip():
                joined.append("")
            continue
        if joined and joined[-1].strip() and stripped[0].islower():
            joined[-1] = f"{joined[-1]} {stripped}"
        else:
            joined.append(raw_line)
    return "\n".join(joined)
