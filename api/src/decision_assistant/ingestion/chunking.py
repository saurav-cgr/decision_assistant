from dataclasses import dataclass
from hashlib import sha256

from decision_assistant.ingestion.parsers import ParsedBlock, ParsedDocument, SourceLocator
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.ingestion.tokenization import TokenCounter, get_token_counter


@dataclass(frozen=True, slots=True)
class PassageDraft:
    sequence_number: int
    content: str
    content_hash: str
    start_offset: int
    end_offset: int
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    group_path: tuple[str, ...]
    boundary_before: str
    block: ParsedBlock
    doc_start: int
    doc_end: int


DEFAULT_TARGET_TOKENS = int(CURRENT_CHUNKING_PROFILE["target_tokens"])
DEFAULT_MAX_TOKENS = int(CURRENT_CHUNKING_PROFILE["max_tokens"])
DEFAULT_OVERLAP_TOKENS = int(CURRENT_CHUNKING_PROFILE["overlap_tokens"])


def chunk_document(
    document: ParsedDocument,
    *,
    token_counter: TokenCounter | None = None,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[PassageDraft]:
    """Create deterministic, token-budgeted structural chunks.

    Chunks never cross hard boundaries (section/page/channel/thread) and never
    combine units from different ``group_path`` values. A heading stays with the
    first body block of its section when the hard limit permits.
    """
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if target_tokens < 1 or target_tokens > max_tokens:
        raise ValueError("target_tokens must be between 1 and max_tokens")
    if overlap_tokens < 0 or overlap_tokens > target_tokens:
        raise ValueError("overlap_tokens must be between 0 and target_tokens")
    if not document.content or not document.blocks:
        return []

    counter = token_counter or get_token_counter()
    units = _build_units(document, counter, max_tokens)
    chunks = _accumulate(units, counter, target_tokens, max_tokens)
    return _build_drafts(chunks, counter, overlap_tokens, max_tokens)


def _build_units(
    document: ParsedDocument,
    counter: TokenCounter,
    max_tokens: int,
) -> list[_Unit]:
    units: list[_Unit] = []
    for block in document.blocks:
        raw_text = block.text
        # Offsets address the normalized document content exactly, so track how
        # much leading whitespace the stored unit text drops from the raw block.
        leading = len(raw_text) - len(raw_text.lstrip("\n "))
        text = raw_text.strip("\n ")
        if not text:
            continue
        base_offset = block.start_offset + leading
        if counter.count(text) <= max_tokens:
            units.append(
                _Unit(
                    text=text,
                    group_path=block.group_path,
                    boundary_before=block.boundary_before,
                    block=block,
                    doc_start=base_offset,
                    doc_end=base_offset + len(text),
                )
            )
            continue
        pieces = _split_oversized(text, counter, max_tokens)
        for index, (rel_start, rel_end) in enumerate(pieces):
            units.append(
                _Unit(
                    text=text[rel_start:rel_end],
                    group_path=block.group_path,
                    boundary_before=block.boundary_before if index == 0 else "none",
                    block=block,
                    doc_start=base_offset + rel_start,
                    doc_end=base_offset + rel_end,
                )
            )
    return units


def _split_oversized(
    text: str,
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[int, int]]:
    """Split ``text`` into exact contiguous ``[start, end)`` spans.

    Sentence boundaries are preserved first; any single sentence that still
    exceeds ``max_tokens`` is further split into exact token-window spans. The
    returned spans partition ``text`` with no trimming or rejoining, so
    concatenating ``text[start:end]`` over every span recovers ``text`` exactly.
    """
    spans: list[tuple[int, int]] = []
    piece_start: int | None = None
    for sent_start, sent_end in _sentence_spans(text):
        if counter.count(text[sent_start:sent_end]) > max_tokens:
            if piece_start is not None:
                spans.append((piece_start, sent_start))
                piece_start = None
            spans.extend(
                _token_window_spans(text, sent_start, sent_end, counter, max_tokens)
            )
            continue
        if piece_start is None:
            piece_start = sent_start
        if counter.count(text[piece_start:sent_end]) > max_tokens:
            spans.append((piece_start, sent_start))
            piece_start = sent_start
    if piece_start is not None:
        spans.append((piece_start, len(text)))
    return spans


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Return exact sentence spans partitioning ``text``.

    Each span ends after the sentence terminator and any following whitespace,
    so the spans are contiguous and cover ``text`` exactly (lossless).
    """
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        index += 1
        if char in ".!?" and (index >= length or text[index].isspace()):
            end = index
            while end < length and text[end].isspace():
                end += 1
            spans.append((start, end))
            start = end
            index = end
    if start < length:
        spans.append((start, length))
    return spans


def _token_window_spans(
    text: str,
    start: int,
    end: int,
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into exact token-window spans."""
    spans: list[tuple[int, int]] = []
    position = start
    while position < end:
        low, high = position + 1, end
        best = position + 1
        while low <= high:
            mid = (low + high) // 2
            if counter.count(text[position:mid]) <= max_tokens:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        if best <= position:
            best = position + 1
        spans.append((position, best))
        position = best
    return spans


def _accumulate(
    units: list[_Unit],
    counter: TokenCounter,
    target_tokens: int,
    max_tokens: int,
) -> list[list[_Unit]]:
    chunks: list[list[_Unit]] = []
    current: list[_Unit] = []

    def finalize() -> None:
        nonlocal current
        if current:
            chunks.append(current)
        current = []

    for unit in units:
        if unit.boundary_before == "hard" and current:
            finalize()
        if current:
            over_group = unit.group_path != current[-1].group_path
            # Count the rendered candidate (units joined by the stored separator)
            # rather than a sum of isolated counts: separator tokens consume the
            # budget too, so no stored passage ever exceeds its maximum.
            over_hard = _tokens(current + [unit], counter) > max_tokens
            over_target = (
                _tokens(current, counter) >= target_tokens
                and unit.boundary_before in ("soft", "hard")
            )
            if over_group or over_hard or over_target:
                finalize()
        current.append(unit)

    finalize()
    return chunks


def _build_drafts(
    chunks: list[list[_Unit]],
    counter: TokenCounter,
    overlap_tokens: int,
    max_tokens: int,
) -> list[PassageDraft]:
    drafts: list[PassageDraft] = []
    for index, chunk in enumerate(chunks):
        units = list(chunk)
        if index > 0:
            overlap = _trailing_units(chunks[index - 1], counter, overlap_tokens)
            if overlap and units:
                # Overlap must never cross a hard or group boundary.
                first_group = units[0].group_path
                overlap = [
                    unit
                    for unit in overlap
                    if unit.group_path == first_group
                    and unit.boundary_before != "hard"
                ]
            if overlap:
                candidate = overlap + units
                if _tokens(candidate, counter) <= max_tokens:
                    units = candidate
        content = _render(units)
        drafts.append(
            PassageDraft(
                sequence_number=index,
                content=content,
                content_hash=sha256(content.encode("utf-8")).hexdigest(),
                start_offset=units[0].doc_start,
                end_offset=units[-1].doc_end,
                locator=_locator_for_units(units),
            )
        )
    return drafts


def _render(units: list[_Unit]) -> str:
    """Serialize units exactly as stored passage content ("\n\n" separator)."""
    return "\n\n".join(unit.text for unit in units)


def _tokens(units: list[_Unit], counter: TokenCounter) -> int:
    return counter.count(_render(units))


def _trailing_units(
    units: list[_Unit],
    counter: TokenCounter,
    overlap_tokens: int,
) -> list[_Unit]:
    trailing: list[_Unit] = []
    total = 0
    for unit in reversed(units):
        unit_tokens = counter.count(unit.text)
        if total + unit_tokens > overlap_tokens:
            break
        trailing.append(unit)
        total += unit_tokens
    trailing.reverse()
    return trailing


def _locator_for_units(units: list[_Unit]) -> SourceLocator:
    blocks = [unit.block for unit in units]
    kinds = {block.locator.get("kind") for block in blocks}
    if kinds & {"slack_message", "teams_message"}:
        messages = [
            block
            for block in blocks
            if block.locator.get("kind") in {"slack_message", "teams_message"}
        ]
        source = "slack" if "slack_message" in kinds else "teams"
        return {
            "kind": "message_range",
            "source": source,
            "first_message_id": messages[0].locator["message_id"],
            "last_message_id": messages[-1].locator["message_id"],
            "message_urls": [block.locator["message_url"] for block in messages],
        }
    if "pdf_page" in kinds:
        return {"kind": "pdf_page", "page": int(blocks[0].locator["page"])}
    if "docx_paragraphs" in kinds:
        return {
            "kind": "docx_paragraphs",
            "start": int(blocks[0].locator["start"]),
            "end": int(blocks[-1].locator["end"]),
        }
    return {
        "kind": "lines",
        "start": int(blocks[0].locator["start"]),
        "end": int(blocks[-1].locator["end"]),
    }

