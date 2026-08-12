from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from docx import Document as open_docx
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from decision_assistant.errors import ApplicationError

LineLocator = dict[str, str | int]
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


def _parse_pdf_document(path: Path) -> ParsedDocument:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise DocumentParseError(
                "pdf_password_protected",
                "Password-protected PDF files are not supported",
            )
        source_blocks = [
            (
                _normalize_extracted_text(
                    _reconstruct_pdf_lines(page.extract_text() or "")
                ),
                {"kind": "pdf_page", "page": page_number},
            )
            for page_number, page in enumerate(reader.pages, start=1)
        ]
    except DocumentParseError:
        raise
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        raise DocumentParseError(
            "pdf_parse_failed",
            "PDF could not be parsed",
        ) from exc

    non_empty_blocks = [block for block in source_blocks if block[0]]
    if not non_empty_blocks:
        raise DocumentParseError(
            "ocr_not_supported",
            "PDF contains no embedded text; OCR is not supported",
        )
    return _assemble_document(path, non_empty_blocks)


def _parse_docx_document(path: Path) -> ParsedDocument:
    try:
        document = open_docx(path)
        source_blocks: list[tuple[str, LineLocator]] = []
        paragraph_number = 0
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                paragraph_number += 1
                _append_docx_paragraph(
                    source_blocks,
                    item.text,
                    paragraph_number,
                )
                continue
            if isinstance(item, Table):
                for row in item.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            paragraph_number += 1
                            _append_docx_paragraph(
                                source_blocks,
                                paragraph.text,
                                paragraph_number,
                            )
    except (BadZipFile, KeyError, OSError, PackageNotFoundError, ValueError) as exc:
        raise DocumentParseError(
            "docx_parse_failed",
            "DOCX could not be parsed",
        ) from exc

    return _assemble_document(path, source_blocks)


def _append_docx_paragraph(
    blocks: list[tuple[str, LineLocator]],
    text: str,
    paragraph_number: int,
) -> None:
    normalized = _normalize_extracted_text(text)
    if normalized:
        blocks.append(
            (
                normalized,
                {
                    "kind": "docx_paragraphs",
                    "start": paragraph_number,
                    "end": paragraph_number,
                },
            )
        )


def _assemble_document(
    path: Path,
    source_blocks: list[tuple[str, LineLocator]],
) -> ParsedDocument:
    content_parts: list[str] = []
    blocks: list[ParsedBlock] = []
    offset = 0
    for text, locator in source_blocks:
        if content_parts:
            content_parts.append("\n\n")
            offset += 2
        start_offset = offset
        content_parts.append(text)
        offset += len(text)
        blocks.append(
            ParsedBlock(
                text=text,
                locator=locator,
                start_offset=start_offset,
                end_offset=offset,
            )
        )
    return ParsedDocument(
        source_path=path,
        content="".join(content_parts),
        blocks=tuple(blocks),
    )


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
