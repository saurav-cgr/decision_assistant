from hashlib import sha256

import pytest

from decision_assistant.ingestion.chunking import PassageDraft
from decision_assistant.ingestion.retrieval_units import (
    build_retrieval_units,
    canonical_decision_unit_kind,
)


def _passage(content: str) -> PassageDraft:
    return PassageDraft(
        sequence_number=3,
        content=content,
        content_hash=sha256(content.encode()).hexdigest(),
        start_offset=20,
        end_offset=20 + len(content),
        locator={"kind": "lines", "start": 3, "end": 3},
        structural_metadata={"group_path": ["heading:one"], "block_types": ["paragraph"]},
    )


def test_passage_strategy_retains_structural_passages() -> None:
    passage = _passage("First sentence. Second sentence.")

    units = build_retrieval_units([passage], strategy="passage_hybrid")

    assert [(unit.kind, unit.parent_index, unit.draft) for unit in units] == [
        ("passage", None, passage)
    ]
    assert canonical_decision_unit_kind("passage_hybrid") == "passage"


@pytest.mark.parametrize("strategy", ["sentence_expanded", "parent_child_merged"])
def test_sentence_strategies_store_exact_linked_sentence_children(strategy: str) -> None:
    passage = _passage("First sentence. Second sentence.")

    units = build_retrieval_units([passage], strategy=strategy)  # type: ignore[arg-type]

    parent, first, second = units
    assert parent.kind == "parent"
    assert [(child.kind, child.parent_index, child.draft.content) for child in (first, second)] == [
        ("sentence", 0, "First sentence."),
        ("sentence", 0, "Second sentence."),
    ]
    assert first.draft.start_offset == passage.start_offset
    assert second.draft.start_offset == passage.start_offset + len("First sentence. ")
    assert first.draft.structural_metadata["parent_sequence_number"] == 3
    assert second.draft.structural_metadata["sentence_index"] == 1
    assert canonical_decision_unit_kind(strategy) == (
        "sentence" if strategy == "sentence_expanded" else "parent"
    )


def test_unknown_strategy_fails_fast() -> None:
    with pytest.raises(ValueError, match="Unknown retrieval unit strategy"):
        build_retrieval_units([], strategy="unknown")  # type: ignore[arg-type]
