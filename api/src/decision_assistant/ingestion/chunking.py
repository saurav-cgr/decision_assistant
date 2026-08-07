from dataclasses import dataclass
from hashlib import sha256

from decision_assistant.ingestion.parsers import LineLocator, ParsedBlock, ParsedDocument


@dataclass(frozen=True, slots=True)
class PassageDraft:
    sequence_number: int
    content: str
    content_hash: str
    start_offset: int
    end_offset: int
    locator: LineLocator


def chunk_document(
    document: ParsedDocument,
    *,
    max_characters: int = 1_500,
    overlap_characters: int = 150,
) -> list[PassageDraft]:
    """Create deterministic chunks, preferring parsed block boundaries."""
    if max_characters <= 0:
        raise ValueError("max_characters must be positive")
    if overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError("overlap_characters must be between 0 and max_characters")
    if not document.content or not document.blocks:
        return []

    drafts: list[PassageDraft] = []
    start = 0
    content_length = len(document.content)

    while start < content_length:
        start = _skip_whitespace(document.content, start)
        if start >= content_length:
            break

        end = _choose_end(document.blocks, start, max_characters, content_length)
        end = _trim_end(document.content, start, end)
        chunk_content = document.content[start:end]
        locator = _locator_for_range(document.blocks, start, end)
        drafts.append(
            PassageDraft(
                sequence_number=len(drafts),
                content=chunk_content,
                content_hash=sha256(chunk_content.encode("utf-8")).hexdigest(),
                start_offset=start,
                end_offset=end,
                locator=locator,
            )
        )

        if end >= content_length:
            break
        start = _choose_next_start(
            document.blocks,
            current_start=start,
            current_end=end,
            overlap_characters=overlap_characters,
        )

    return drafts


def _choose_end(
    blocks: tuple[ParsedBlock, ...],
    start: int,
    max_characters: int,
    content_length: int,
) -> int:
    hard_end = min(start + max_characters, content_length)
    boundary_ends = [
        block.end_offset
        for block in blocks
        if start < block.end_offset <= hard_end
    ]
    return max(boundary_ends, default=hard_end)


def _choose_next_start(
    blocks: tuple[ParsedBlock, ...],
    *,
    current_start: int,
    current_end: int,
    overlap_characters: int,
) -> int:
    if overlap_characters == 0:
        return current_end

    overlap_floor = current_end - overlap_characters
    boundary_starts = [
        block.start_offset
        for block in blocks
        if max(current_start + 1, overlap_floor) <= block.start_offset < current_end
    ]
    if boundary_starts:
        return min(boundary_starts)

    ended_on_boundary = any(block.end_offset == current_end for block in blocks)
    if ended_on_boundary:
        return current_end
    return max(current_start + 1, overlap_floor)


def _locator_for_range(
    blocks: tuple[ParsedBlock, ...],
    start: int,
    end: int,
) -> LineLocator:
    covered = [
        block
        for block in blocks
        if block.start_offset < end and block.end_offset > start
    ]
    return {
        "kind": "lines",
        "start": int(covered[0].locator["start"]),
        "end": int(covered[-1].locator["end"]),
    }


def _skip_whitespace(content: str, offset: int) -> int:
    while offset < len(content) and content[offset].isspace():
        offset += 1
    return offset


def _trim_end(content: str, start: int, end: int) -> int:
    while end > start and content[end - 1].isspace():
        end -= 1
    return end
