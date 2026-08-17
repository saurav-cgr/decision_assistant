from dataclasses import dataclass
from math import ceil
from statistics import median
from decimal import Decimal
from typing import Literal, Sequence

Expectation = Literal["answer", "abstain", "partial"]


@dataclass(frozen=True, slots=True)
class CitationRates:
    structural_validity: float
    correctness: float


@dataclass(frozen=True, slots=True)
class LatencySummary:
    median_ms: float
    p95_ms: float


def top_five_hit_rate(
    retrieved: Sequence[Sequence[str]],
    expected: Sequence[set[str]],
) -> float:
    _require_same_length(retrieved, expected)
    if not retrieved:
        return 0.0
    hits = sum(bool(set(items[:5]) & gold) for items, gold in zip(retrieved, expected))
    return hits / len(retrieved)


def mean_reciprocal_rank(
    retrieved: Sequence[Sequence[str]],
    expected: Sequence[set[str]],
) -> float:
    _require_same_length(retrieved, expected)
    if not retrieved:
        return 0.0
    reciprocal_ranks: list[float] = []
    for items, gold in zip(retrieved, expected):
        rank = next(
            (index for index, item in enumerate(items, start=1) if item in gold),
            None,
        )
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def citation_rates(checks: Sequence[dict[str, bool]]) -> CitationRates:
    if not checks:
        return CitationRates(0.0, 0.0)
    structural = sum(bool(check.get("structurally_valid")) for check in checks)
    correct = sum(
        bool(check.get("structurally_valid")) and bool(check.get("supports_claim"))
        for check in checks
    )
    return CitationRates(
        structural_validity=structural / len(checks),
        correctness=correct / len(checks),
    )


def gold_citation_coverage(
    checks_by_question: Sequence[Sequence[dict[str, object]]],
) -> float:
    if not checks_by_question:
        return 0.0
    covered = sum(
        any(bool(check.get("matches_gold_evidence")) for check in checks)
        for checks in checks_by_question
    )
    return covered / len(checks_by_question)


def answer_abstention_accuracy(
    expected: Sequence[Expectation],
    actual: Sequence[Expectation],
) -> float:
    _require_same_length(expected, actual)
    if not expected:
        return 0.0
    return sum(wanted == observed for wanted, observed in zip(expected, actual)) / len(
        expected
    )


def facet_abstention_accuracy(
    expected: Sequence[dict[str, Expectation]],
    actual: Sequence[dict[str, Expectation]],
) -> float:
    _require_same_length(expected, actual)
    comparisons = [
        wanted == observed.get(facet)
        for wanted_facets, observed in zip(expected, actual)
        for facet, wanted in wanted_facets.items()
    ]
    return sum(comparisons) / len(comparisons) if comparisons else 0.0


def latency_summary(latencies_ms: Sequence[float]) -> LatencySummary:
    if not latencies_ms:
        return LatencySummary(0.0, 0.0)
    ordered = sorted(float(value) for value in latencies_ms)
    p95_index = max(ceil(0.95 * len(ordered)) - 1, 0)
    return LatencySummary(
        median_ms=float(median(ordered)),
        p95_ms=ordered[p95_index],
    )


def claim_support_rate(supported: Sequence[bool]) -> float:
    return sum(bool(value) for value in supported) / len(supported) if supported else 0.0


def decision_rank_accuracy(
    expected_winners: Sequence[str], actual_winners: Sequence[str]
) -> float:
    _require_same_length(expected_winners, actual_winners)
    if not expected_winners:
        return 0.0
    return sum(
        expected == actual
        for expected, actual in zip(expected_winners, actual_winners)
    ) / len(expected_winners)


def mean_evidence_backed_weight(
    weights: Sequence[Decimal | float],
) -> float:
    return float(sum((Decimal(str(weight)) for weight in weights), Decimal())) / len(
        weights
    ) if weights else 0.0


def sensitivity_stability_accuracy(
    expected: Sequence[bool], actual: Sequence[bool]
) -> float:
    _require_same_length(expected, actual)
    if not expected:
        return 0.0
    return sum(
        wanted == observed for wanted, observed in zip(expected, actual)
    ) / len(expected)


def _require_same_length(left: Sequence[object], right: Sequence[object]) -> None:
    if len(left) != len(right):
        raise ValueError("metric inputs must have equal lengths")
