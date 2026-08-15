import hashlib
from pathlib import Path

from decision_assistant.ingestion.chunking import chunk_document
from decision_assistant.ingestion.parsers import (
    ParsedBlock,
    ParsedDocument,
    parse_document,
)
from decision_assistant.ingestion.tokenization import (
    TiktokenCounter,
    get_token_counter,
)

FIXTURE = Path("tests/fixtures/meeting.md")
COUNTER = TiktokenCounter()


def _write(tmp_path: Path, content: str, name: str = "doc.md") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_token_counts_are_stable_for_diverse_text() -> None:
    samples = [
        "plain ascii text with spaces",
        "héllo wörld ünïcode",
        "def f(x):\n    return x + 1",
        "https://example.com/very/long/path?q=1&r=2",
        "x" * 5000,
    ]
    for sample in samples:
        assert COUNTER.count(sample) == COUNTER.count(sample)


def test_offline_counter_returns_stable_counts() -> None:
    counter = get_token_counter()
    assert counter.count("offline check") > 0


def test_chunks_have_reproducible_hashes() -> None:
    first = chunk_document(
        parse_document(FIXTURE),
        token_counter=COUNTER,
        target_tokens=120,
        max_tokens=200,
        overlap_tokens=20,
    )
    second = chunk_document(
        parse_document(FIXTURE),
        token_counter=COUNTER,
        target_tokens=120,
        max_tokens=200,
        overlap_tokens=20,
    )

    assert [(chunk.content, chunk.content_hash) for chunk in first] == [
        (chunk.content, chunk.content_hash) for chunk in second
    ]
    assert all(
        chunk.content_hash
        == hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        for chunk in first
    )


def test_chunks_respect_target_max_sequence_and_offsets(tmp_path: Path) -> None:
    content = "Paragraph one.\n\n" + "\n\n".join(
        f"Body sentence {index} with supporting detail text." for index in range(40)
    )
    chunks = chunk_document(
        parse_document(_write(tmp_path, content)),
        token_counter=COUNTER,
        target_tokens=60,
        max_tokens=100,
        overlap_tokens=15,
    )

    assert len(chunks) > 1
    assert all(COUNTER.count(chunk.content) <= 100 for chunk in chunks)
    assert [chunk.sequence_number for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.start_offset < chunk.end_offset for chunk in chunks)
    assert all(chunk.locator["kind"] == "lines" for chunk in chunks)
    assert all(chunk.locator["start"] <= chunk.locator["end"] for chunk in chunks)


def test_hard_boundaries_are_never_crossed(tmp_path: Path) -> None:
    content = (
        "## Alpha\n\n"
        + "\n\n".join(f"Alpha detail {index}." for index in range(30))
        + "\n\n## Beta\n\n"
        + "\n\n".join(f"Beta detail {index}." for index in range(30))
    )
    chunks = chunk_document(
        parse_document(_write(tmp_path, content)),
        token_counter=COUNTER,
        target_tokens=200,
        max_tokens=400,
    )

    for chunk in chunks:
        assert not ("Alpha" in chunk.content and "Beta" in chunk.content)
    assert any("Alpha" in chunk.content for chunk in chunks)
    assert any("Beta" in chunk.content for chunk in chunks)


def test_heading_stays_with_first_body_block(tmp_path: Path) -> None:
    content = "## Architecture\n\nThe team chose PostgreSQL.\n"
    chunks = chunk_document(
        parse_document(_write(tmp_path, content)),
        token_counter=COUNTER,
    )

    assert chunks
    assert chunks[0].content.startswith("Architecture")
    assert "PostgreSQL" in chunks[0].content


def test_oversized_block_is_preserved_through_offsets(tmp_path: Path) -> None:
    long_text = "word " * 3000
    content = f"# Title\n\n{long_text.strip()}\n"
    chunks = chunk_document(
        parse_document(_write(tmp_path, content)),
        token_counter=COUNTER,
        target_tokens=200,
        max_tokens=300,
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert COUNTER.count(chunk.content) <= 300
    # Removing the inserted "\n\n" separators must recover the original source
    # exactly: no loss and no silent truncation.
    compacted = "\n\n".join(chunk.content for chunk in chunks).replace("\n\n", "")
    assert long_text.strip() in compacted


def test_chunking_preserves_pdf_page_locator_kind() -> None:
    pdf = parse_document(Path("tests/fixtures/text.pdf"))

    chunks = chunk_document(pdf, token_counter=COUNTER)

    assert chunks
    assert all(chunk.locator["kind"] == "pdf_page" for chunk in chunks)
    assert all("page" in chunk.locator for chunk in chunks)


def test_chunking_preserves_docx_paragraph_locator_kind() -> None:
    docx = parse_document(Path("tests/fixtures/decision.docx"))

    chunks = chunk_document(docx, token_counter=COUNTER)

    assert chunks
    assert all(chunk.locator["kind"] == "docx_paragraphs" for chunk in chunks)
    assert all(chunk.locator["start"] <= chunk.locator["end"] for chunk in chunks)


def test_conversation_chunks_never_mix_channels() -> None:
    blocks: list[ParsedBlock] = []
    offset = 0
    for channel in ("C1", "C2"):
        group = (f"channel:{channel}", "thread:t")
        for message_id, text in (
            ("m1", "First decision in channel."),
            ("m2", "Second supporting detail."),
        ):
            if blocks:
                offset += 2
            locator = {
                "kind": "slack_message",
                "workspace_id": "W",
                "channel_id": channel,
                "thread_id": "t",
                "message_id": message_id,
                "message_url": f"https://x/{channel}/{message_id}",
            }
            start = offset
            offset += len(text)
            blocks.append(
                ParsedBlock(
                    text=text,
                    block_type="message",
                    group_path=group,
                    boundary_before="soft",
                    attributes={},
                    locator=locator,
                    start_offset=start,
                    end_offset=offset,
                )
            )
    document = ParsedDocument(
        source_path=Path("conversation"),
        content="\n\n".join(block.text for block in blocks),
        blocks=tuple(blocks),
    )

    chunks = chunk_document(document, token_counter=COUNTER)

    assert chunks
    for chunk in chunks:
        urls = chunk.locator["message_urls"]
        assert urls
        channels = {url.split("/")[3] for url in urls}
        assert len(channels) == 1
