from collections.abc import Iterable
from pathlib import Path

from decision_assistant.ingestion.parsers import (
    AttributeValue,
    Boundary,
    DocumentParseError,
    ParsedDocument,
    SourceLocator,
    _SourceBlock,
    _assemble_document,
    _heading_key,
    _normalize_extracted_text,
)


def parse_docling_pdf(path: Path) -> ParsedDocument:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import ConversionStatus
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TesseractCliOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        artifacts_path="/opt/docling-models",
        enable_remote_services=False,
        do_ocr=True,
        ocr_options=TesseractCliOcrOptions(lang=["eng"]),
    )
    try:
        result = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            }
        ).convert(path)
        if result.status is not ConversionStatus.SUCCESS:
            raise DocumentParseError(*docling_failure(result.errors))
        source_blocks = docling_source_blocks(result.document)
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(*docling_failure((exc,))) from exc

    if not source_blocks:
        raise DocumentParseError("pdf_parse_failed", "PDF could not be parsed")
    return _assemble_document(path, source_blocks)


def docling_failure(errors: Iterable[object]) -> tuple[str, str]:
    details = " ".join(str(error).lower() for error in errors)
    if "ocr" in details:
        return "pdf_ocr_failed", "PDF OCR failed"
    if "layout" in details or "pipeline" in details:
        return "pdf_layout_failed", "PDF layout analysis failed"
    return "pdf_parse_failed", "PDF could not be parsed"


def docling_source_blocks(document: object) -> list[_SourceBlock]:
    blocks: list[_SourceBlock] = []
    heading_stack: list[tuple[int, str]] = []
    heading_counts: dict[tuple[int, str], int] = {}
    previous_page: int | None = None

    for item, _ in document.iterate_items():
        label = str(item.label.value)
        if label in {"section_header", "title"}:
            block_type = "heading"
            level = int(getattr(item, "level", 1))
            text = _normalize_extracted_text(item.text)
            if not text:
                continue
            key = _heading_key(level, text, heading_counts)
            heading_stack[:] = [entry for entry in heading_stack if entry[0] < level]
            heading_stack.append((level, key))
            attributes: dict[str, AttributeValue] = {"level": level}
        elif label == "list_item":
            block_type = "list_item"
            text = _normalize_extracted_text(item.text)
            attributes = {}
        elif label in {"table", "document_index"}:
            block_type = "table_cell"
            text = _normalize_extracted_text(item.export_to_markdown(document))
            attributes = {}
        else:
            block_type = "paragraph"
            text = _normalize_extracted_text(getattr(item, "text", ""))
            attributes = {}
        if not text:
            continue

        locator = docling_locator(document, item)
        page = int(locator["page"])
        boundary: Boundary = "none"
        if blocks:
            boundary = (
                "hard"
                if page != previous_page or block_type == "heading"
                else "soft"
            )
        blocks.append(
            _SourceBlock(
                text=text,
                block_type=block_type,
                group_path=tuple(key for _, key in heading_stack),
                boundary_before=boundary,
                attributes=attributes,
                locator=locator,
            )
        )
        previous_page = page
    return blocks


def docling_locator(document: object, item: object) -> SourceLocator:
    provenance = item.prov[0]
    page = int(provenance.page_no)
    size = document.pages[page].size
    box = provenance.bbox
    if str(box.coord_origin.value) == "BOTTOMLEFT":
        top = size.height - box.t
        bottom = size.height - box.b
    else:
        top = box.t
        bottom = box.b
    return {
        "kind": "pdf_region",
        "page": page,
        "bbox": [
            round(box.l / size.width, 6),
            round(top / size.height, 6),
            round(box.r / size.width, 6),
            round(bottom / size.height, 6),
        ],
    }
