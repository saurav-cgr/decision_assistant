from dataclasses import fields
from inspect import Parameter, signature
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from decision_assistant.ingestion.chunking import chunk_document
from decision_assistant.ingestion.parsers import (
    DocumentParseError,
    ParsedDocument,
    _SourceBlock,
    _docling_locator,
    _docling_source_blocks,
    parse_document,
)


TEXT_PDF = Path("tests/fixtures/text.pdf")


class _FakeDoclingDocument:
    def __init__(self, *items: object) -> None:
        self.items = items
        self.pages = {
            1: SimpleNamespace(size=SimpleNamespace(width=200, height=400)),
            2: SimpleNamespace(size=SimpleNamespace(width=200, height=400)),
        }

    def iterate_items(self):
        return ((item, 0) for item in self.items)


class _FakeTable:
    label = SimpleNamespace(value="table")

    def __init__(self, text: str, page: int) -> None:
        self.text = text
        self.prov = [_fake_provenance(page)]

    def export_to_markdown(self, document: object) -> str:
        return self.text


def _fake_provenance(page: int) -> object:
    return SimpleNamespace(
        page_no=page,
        bbox=SimpleNamespace(
            l=20,
            t=360,
            r=180,
            b=320,
            coord_origin=SimpleNamespace(value="BOTTOMLEFT"),
        ),
    )


def test_frozen_parser_and_chunker_contract() -> None:
    assert [field.name for field in fields(ParsedDocument)] == [
        "source_path",
        "content",
        "blocks",
    ]
    assert [field.name for field in fields(_SourceBlock)] == [
        "text",
        "block_type",
        "group_path",
        "boundary_before",
        "attributes",
        "locator",
    ]
    assert list(signature(parse_document).parameters) == ["path"]
    assert [
        (parameter.name, parameter.kind)
        for parameter in signature(chunk_document).parameters.values()
    ] == [
        ("document", Parameter.POSITIONAL_OR_KEYWORD),
        ("token_counter", Parameter.KEYWORD_ONLY),
        ("target_tokens", Parameter.KEYWORD_ONLY),
        ("max_tokens", Parameter.KEYWORD_ONLY),
        ("overlap_tokens", Parameter.KEYWORD_ONLY),
    ]


def test_docling_maps_items_and_preserves_page_boundaries() -> None:
    def item(label: str, text: str, page: int, **values: object) -> object:
        return SimpleNamespace(
            label=SimpleNamespace(value=label),
            text=text,
            prov=[_fake_provenance(page)],
            **values,
        )

    blocks = _docling_source_blocks(
        _FakeDoclingDocument(
            item("section_header", "Overview", 1, level=1),
            item("text", "Paragraph", 1),
            item("list_item", "First item", 1),
            _FakeTable("| A |\n|---|\n| B |", 2),
        )
    )

    assert [block.block_type for block in blocks] == [
        "heading",
        "paragraph",
        "list_item",
        "table_cell",
    ]
    assert [block.boundary_before for block in blocks] == [
        "none",
        "soft",
        "soft",
        "hard",
    ]
    assert blocks[0].attributes == {"level": 1}
    assert all(block.group_path == ("heading-1:overview#1",) for block in blocks)
    assert [block.locator for block in blocks] == [
        {
            "kind": "pdf_region",
            "page": page,
            "bbox": [0.1, 0.1, 0.9, 0.2],
        }
        for page in [1, 1, 1, 2]
    ]


def test_docling_preserves_reading_order() -> None:
    def item(text: str, page: int) -> object:
        return SimpleNamespace(
            label=SimpleNamespace(value="text"),
            text=text,
            prov=[_fake_provenance(page)],
        )

    blocks = _docling_source_blocks(
        _FakeDoclingDocument(
            item("First column", 1),
            item("Second column", 1),
            item("Next page", 2),
        )
    )

    assert [block.text for block in blocks] == [
        "First column",
        "Second column",
        "Next page",
    ]
    assert [block.boundary_before for block in blocks] == ["none", "soft", "hard"]


def test_docling_locator_normalizes_top_left_bbox() -> None:
    document = _FakeDoclingDocument()
    item = SimpleNamespace(
        prov=[
            SimpleNamespace(
                page_no=1,
                bbox=SimpleNamespace(
                    l=20,
                    t=40,
                    r=180,
                    b=120,
                    coord_origin=SimpleNamespace(value="TOPLEFT"),
                ),
            )
        ]
    )

    assert _docling_locator(document, item) == {
        "kind": "pdf_region",
        "page": 1,
        "bbox": [0.1, 0.1, 0.9, 0.3],
    }


def test_pdf_parser_dispatches_to_docling(monkeypatch: pytest.MonkeyPatch) -> None:
    from decision_assistant.ingestion import parsers

    sentinel = ParsedDocument(TEXT_PDF, "docling", ())
    monkeypatch.setattr(parsers, "_parse_docling_pdf_document", lambda path: sentinel)

    assert parse_document(TEXT_PDF) is sentinel


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            SimpleNamespace(error_message="OCR engine failed"),
            "pdf_ocr_failed",
            "PDF OCR failed",
        ),
        (
            SimpleNamespace(module_name="layout pipeline"),
            "pdf_layout_failed",
            "PDF layout analysis failed",
        ),
        (
            SimpleNamespace(error_message="unexpected failure"),
            "pdf_parse_failed",
            "PDF could not be parsed",
        ),
    ],
)
def test_docling_failures_are_sanitized(
    error: object,
    code: str,
    message: str,
) -> None:
    from decision_assistant.ingestion.parsers import _docling_failure

    assert _docling_failure((error,)) == (code, message)


@pytest.mark.asyncio
async def test_docling_parse_runs_in_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decision_assistant.ingestion import service

    caller_thread = threading.get_ident()
    worker_threads: list[int] = []
    sentinel = object()
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(model_timeout_seconds=1),
    )
    monkeypatch.setattr(
        service,
        "parse_document",
        lambda path: worker_threads.append(threading.get_ident()) or sentinel,
    )

    assert await service._parse_for_ingestion(TEXT_PDF) is sentinel
    assert worker_threads and worker_threads[0] != caller_thread


@pytest.mark.asyncio
async def test_docling_parse_timeout_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decision_assistant.ingestion import service

    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(model_timeout_seconds=0.01),
    )

    def hang(path: Path) -> None:
        started.set()
        release.wait()

    monkeypatch.setattr(service, "parse_document", hang)
    task = asyncio.create_task(service._parse_for_ingestion(TEXT_PDF))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(DocumentParseError) as error:
            await task
    finally:
        release.set()

    assert error.value.code == "pdf_parse_timeout"
    assert error.value.retryable is False


@pytest.mark.asyncio
async def test_non_pdf_sources_skip_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decision_assistant.ingestion import service

    caller_thread = threading.get_ident()
    recorded_threads: list[int] = []
    sentinel = object()
    monkeypatch.setattr(
        service,
        "parse_document",
        lambda path: recorded_threads.append(threading.get_ident()) or sentinel,
    )

    result = await service._parse_for_ingestion(Path("tests/fixtures/meeting.md"))

    assert result is sentinel
    assert recorded_threads == [caller_thread]


def test_pdf_without_extractable_text_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docling.datamodel.document import ConversionStatus

    class _FakeConverter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def convert(self, path: Path) -> SimpleNamespace:
            return SimpleNamespace(
                status=ConversionStatus.SUCCESS,
                document=_FakeDoclingDocument(),
                errors=(),
            )

    monkeypatch.setattr(
        "docling.document_converter.DocumentConverter", _FakeConverter
    )

    with pytest.raises(DocumentParseError) as error:
        parse_document(TEXT_PDF)

    assert error.value.code == "pdf_no_extractable_text"
    assert error.value.message == "PDF contains no extractable text"
    assert "docling-parse" not in error.value.message
    assert "PDFium" not in error.value.message


def test_encrypted_pdf_returns_password_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reportlab.lib.pdfencrypt
    from reportlab.pdfgen import canvas

    encrypted = tmp_path / "encrypted.pdf"
    encryption = reportlab.lib.pdfencrypt.StandardEncryption("secret", canPrint=0)
    pdf = canvas.Canvas(str(encrypted), encrypt=encryption)
    pdf.drawString(72, 720, "Confidential")
    pdf.save()

    def _fail_if_reached(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "Docling conversion should not run for an encrypted PDF"
        )

    monkeypatch.setattr(
        "docling.document_converter.DocumentConverter", _fail_if_reached
    )

    with pytest.raises(DocumentParseError) as error:
        parse_document(encrypted)

    assert error.value.code == "pdf_password_protected"
    assert error.value.retryable is False
    assert "docling-parse" not in error.value.message
    assert "PDFium" not in error.value.message


def test_corrupt_pdf_returns_parser_specific_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a PDF")

    with pytest.raises(DocumentParseError) as error:
        parse_document(corrupt)

    assert error.value.code == "pdf_parse_failed"
    assert "docling-parse" not in error.value.message
    assert "PDFium" not in error.value.message
