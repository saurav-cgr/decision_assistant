"""Build persisted retrieval units from structural passage drafts."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from decision_assistant.ingestion.chunking import PassageDraft, sentence_spans

RetrievalUnitStrategy = Literal[
    "passage_hybrid",
    "sentence_expanded",
    "parent_child_merged",
]


@dataclass(frozen=True, slots=True)
class RetrievalUnitDraft:
    draft: PassageDraft
    kind: Literal["passage", "parent", "sentence"]
    parent_index: int | None = None


def build_retrieval_units(
    passages: list[PassageDraft],
    *,
    strategy: RetrievalUnitStrategy,
) -> list[RetrievalUnitDraft]:
    """Return citation-valid units for one retrieval strategy.

    Sentence-based strategies retain structural passages as stored parents. Their
    children are exact trimmed sentence slices of each parent, allowing later
    expansion or parent merging without synthesizing citation text at query time.
    """
    if strategy == "passage_hybrid":
        return [RetrievalUnitDraft(draft, "passage") for draft in passages]
    if strategy not in {"sentence_expanded", "parent_child_merged"}:
        raise ValueError(f"Unknown retrieval unit strategy: {strategy}")

    units = [RetrievalUnitDraft(draft, "parent") for draft in passages]
    for parent_index, parent in enumerate(passages):
        for sentence_index, (start, end) in enumerate(sentence_spans(parent.content)):
            raw_content = parent.content[start:end]
            leading = len(raw_content) - len(raw_content.lstrip())
            content = raw_content.strip()
            if not content:
                continue
            child_start = parent.start_offset + start + leading
            child_draft = PassageDraft(
                sequence_number=parent.sequence_number,
                content=content,
                content_hash=sha256(content.encode("utf-8")).hexdigest(),
                start_offset=child_start,
                end_offset=child_start + len(content),
                locator=parent.locator,
                structural_metadata={
                    **parent.structural_metadata,
                    "parent_sequence_number": parent.sequence_number,
                    "sentence_index": sentence_index,
                },
            )
            units.append(
                RetrievalUnitDraft(child_draft, "sentence", parent_index)
            )
    return units


def canonical_decision_unit_kind(strategy: RetrievalUnitStrategy) -> str:
    """Select the evidence unit supplied to decision extraction."""
    if strategy == "passage_hybrid":
        return "passage"
    return "sentence" if strategy == "sentence_expanded" else "parent"
