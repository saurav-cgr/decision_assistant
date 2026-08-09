from dataclasses import dataclass
from typing import Generic, Hashable, TypeVar

ItemId = TypeVar("ItemId", bound=Hashable)


@dataclass(frozen=True, slots=True)
class FusedResult(Generic[ItemId]):
    id: ItemId
    score: float
    source_ranks: dict[str, int]


def reciprocal_rank_fusion(
    ranked_ids: dict[str, list[ItemId]],
    *,
    k: int = 60,
) -> list[FusedResult[ItemId]]:
    if k < 0:
        raise ValueError("k must be non-negative")

    scores: dict[ItemId, float] = {}
    source_ranks: dict[ItemId, dict[str, int]] = {}
    first_seen: dict[ItemId, int] = {}

    for source, identifiers in ranked_ids.items():
        seen_in_source: set[ItemId] = set()
        for rank, identifier in enumerate(identifiers, start=1):
            if identifier in seen_in_source:
                continue
            seen_in_source.add(identifier)
            first_seen.setdefault(identifier, len(first_seen))
            scores[identifier] = scores.get(identifier, 0.0) + (1 / (k + rank))
            source_ranks.setdefault(identifier, {})[source] = rank

    ordered = sorted(
        scores,
        key=lambda identifier: (-scores[identifier], first_seen[identifier]),
    )
    return [
        FusedResult(
            id=identifier,
            score=scores[identifier],
            source_ranks=source_ranks[identifier],
        )
        for identifier in ordered
    ]
