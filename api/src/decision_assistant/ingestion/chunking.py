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
        text = block.text.strip("\n ")
        if not text:
            continue
        if counter.count(text) <= max_tokens:
            units.append(
                _Unit(
                    text=text,
                    group_path=block.group_path,
                    boundary_before=block.boundary_before,
                    block=block,
                    doc_start=block.start_offset,
                    doc_end=block.end_offset,
                )
            )
            continue
        pieces = _split_oversized(text, counter, max_tokens)
        running = 0
        for index, piece in enumerate(pieces):
            start = block.start_offset + running
            running += len(piece)
            units.append(
                _Unit(
                    text=piece,
                    group_path=block.group_path,
                    boundary_before=block.boundary_before if index == 0 else "none",
                    block=block,
                    doc_start=start,
                    doc_end=start + len(piece),
                )
            )
    return units


def _split_oversized(
    text: str,
    counter: TokenCounter,
    max_tokens: int,
) -> list[str]:
    sentences = _split_sentences(text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if counter.count(sentence) > max_tokens:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_by_tokens(sentence, counter, max_tokens))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if counter.count(candidate) > max_tokens:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    current = ""
    index = 0
    while index < len(text):
        char = text[index]
        current += char
        if char in ".!?" and (
            index + 1 >= len(text) or text[index + 1].isspace()
        ):
            parts.append(current.strip())
            current = ""
        index += 1
    if current.strip():
        parts.append(current.strip())
    return [part for part in parts if part]


def _split_by_tokens(
    text: str,
    counter: TokenCounter,
    max_tokens: int,
) -> list[str]:
    if counter.count(text) <= max_tokens:
        return [text]
    pieces: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        low, high = start + 1, length
        best = start + 1
        while low <= high:
            mid = (low + high) // 2
            if counter.count(text[start:mid]) <= max_tokens:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        if best <= start:
            best = start + 1
        pieces.append(text[start:best])
        start = best
    return pieces


def _accumulate(
    units: list[_Unit],
    counter: TokenCounter,
    target_tokens: int,
    max_tokens: int,
) -> list[list[_Unit]]:
    chunks: list[list[_Unit]] = []
    current: list[_Unit] = []
    current_tokens = 0

    def finalize() -> None:
        nonlocal current, current_tokens
        if current:
            chunks.append(current)
        current = []
        current_tokens = 0

    for unit in units:
        unit_tokens = counter.count(unit.text)
        if unit.boundary_before == "hard" and current:
            finalize()
        if current:
            over_group = unit.group_path != current[-1].group_path
            over_hard = current_tokens + unit_tokens > max_tokens
            over_target = (
                current_tokens >= target_tokens
                and unit.boundary_before in ("soft", "hard")
            )
            if over_group or over_hard or over_target:
                finalize()
        current.append(unit)
        current_tokens += unit_tokens

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
        content = "\n\n".join(unit.text for unit in units)
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


def _tokens(units: list[_Unit], counter: TokenCounter) -> int:
    return sum(counter.count(unit.text) for unit in units)


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

