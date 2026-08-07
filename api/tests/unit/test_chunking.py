import hashlib
from pathlib import Path

from decision_assistant.ingestion.chunking import chunk_document
from decision_assistant.ingestion.parsers import parse_document

FIXTURE = Path("tests/fixtures/meeting.md")


def test_chunks_have_reproducible_hashes() -> None:
    first = chunk_document(parse_document(FIXTURE), max_characters=240)
    second = chunk_document(parse_document(FIXTURE), max_characters=240)

    assert [(chunk.content, chunk.content_hash) for chunk in first] == [
        (chunk.content, chunk.content_hash) for chunk in second
    ]
    assert all(
        chunk.content_hash == hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        for chunk in first
    )


def test_chunks_respect_boundaries_size_and_source_locators() -> None:
    chunks = chunk_document(
        parse_document(FIXTURE),
        max_characters=240,
        overlap_characters=40,
    )

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 240 for chunk in chunks)
    assert [chunk.sequence_number for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.start_offset < chunk.end_offset for chunk in chunks)
    assert all(chunk.locator["kind"] == "lines" for chunk in chunks)
    assert all(chunk.locator["start"] <= chunk.locator["end"] for chunk in chunks)
