from collections import defaultdict
from decimal import Decimal

from decision_assistant.decision_analysis.schemas import (
    CriterionBreakdown,
    CriterionValue,
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
    DecisionCriterion,
    DecisionVerification,
    EvidenceCoverage,
    RankedOption,
    ScoreContribution,
    ScoreInput,
    ScoreProvenance,
    SensitivityResult,
    SensitivitySample,
    StabilityLabel,
)

ZERO = Decimal("0")
ONE = Decimal("1")


def calculate_decision(request: DecisionAnalysisRequest) -> DecisionAnalysisResponse:
    scores = _score_index(request.scores)
    ranked_options, breakdowns, tie_groups = _rank(
        request,
        scores=scores,
        weights={criterion.id: criterion.weight for criterion in request.criteria},
    )
    sensitivity = (
        _sensitivity(request, scores, ranked_options[0].option_id)
        if request.sensitivity is not None
        else None
    )
    coverage = _coverage(request)
    warnings = _warnings(breakdowns, coverage)
    return DecisionAnalysisResponse(
        ranked_options=ranked_options,
        tie_groups=tie_groups,
        criterion_breakdowns=breakdowns,
        sensitivity=sensitivity,
        evidence_coverage=coverage,
        verification=DecisionVerification(valid=True, warnings=warnings),
    )


def _score_index(scores: list[ScoreInput]) -> dict[tuple[str, str], ScoreInput]:
    return {(score.option_id, score.criterion_id): score for score in scores}


def _rank(
    request: DecisionAnalysisRequest,
    *,
    scores: dict[tuple[str, str], ScoreInput],
    weights: dict[str, Decimal],
) -> tuple[list[RankedOption], list[CriterionBreakdown], list[list[str]]]:
    normalized: dict[tuple[str, str], Decimal] = {}
    breakdowns: list[CriterionBreakdown] = []
    for criterion in request.criteria:
        values = [scores[(option.id, criterion.id)].value for option in request.options]
        minimum, maximum = min(values), max(values)
        equal_values = minimum == maximum
        criterion_values: list[CriterionValue] = []
        for option in request.options:
            score = scores[(option.id, criterion.id)]
            normalized_value = _normalize(
                score.value,
                minimum=minimum,
                maximum=maximum,
                is_benefit=criterion.direction == "benefit",
            )
            normalized[(option.id, criterion.id)] = normalized_value
            criterion_values.append(
                CriterionValue(
                    option_id=option.id,
                    raw_value=score.value,
                    normalized_value=normalized_value,
                    provenance=score.provenance,
                )
            )
        breakdowns.append(
            CriterionBreakdown(
                criterion_id=criterion.id,
                weight=weights[criterion.id],
                direction=criterion.direction,
                values=criterion_values,
                equal_values=equal_values,
            )
        )

    unsorted: list[RankedOption] = []
    for option in request.options:
        contributions = [
            ScoreContribution(
                criterion_id=criterion.id,
                raw_value=scores[(option.id, criterion.id)].value,
                normalized_value=normalized[(option.id, criterion.id)],
                weighted_contribution=weights[criterion.id]
                * normalized[(option.id, criterion.id)],
                provenance=scores[(option.id, criterion.id)].provenance,
            )
            for criterion in request.criteria
        ]
        unsorted.append(
            RankedOption(
                option_id=option.id,
                rank=0,
                total_score=sum(
                    (contribution.weighted_contribution for contribution in contributions),
                    ZERO,
                ),
                contributions=contributions,
            )
        )
    ordered = sorted(unsorted, key=lambda item: item.total_score, reverse=True)
    ranked = [item.model_copy(update={"rank": index}) for index, item in enumerate(ordered, 1)]
    return ranked, breakdowns, _tie_groups(ranked)


def _normalize(
    value: Decimal,
    *,
    minimum: Decimal,
    maximum: Decimal,
    is_benefit: bool,
) -> Decimal:
    if minimum == maximum:
        return ONE
    denominator = maximum - minimum
    return (value - minimum) / denominator if is_benefit else (maximum - value) / denominator


def _tie_groups(ranked: list[RankedOption]) -> list[list[str]]:
    groups: dict[Decimal, list[str]] = defaultdict(list)
    for option in ranked:
        groups[option.total_score].append(option.option_id)
    return [group for group in groups.values() if len(group) > 1]


def _sensitivity(
    request: DecisionAnalysisRequest,
    scores: dict[tuple[str, str], ScoreInput],
    baseline_winner: str,
) -> SensitivityResult:
    assert request.sensitivity is not None
    samples: list[SensitivitySample] = []
    reversing: set[str] = set()
    baseline_weights = {criterion.id: criterion.weight for criterion in request.criteria}
    positive_criteria = [criterion for criterion in request.criteria if criterion.weight > ZERO]
    for criterion in positive_criteria:
        for varied_weight in _sample_weights(criterion.weight, request.sensitivity.range_percent, request.sensitivity.sample_count):
            adjusted = _rebalance_weights(baseline_weights, criterion, varied_weight)
            ranked, _, _ = _rank(request, scores=scores, weights=adjusted)
            winner = ranked[0].option_id
            changed = winner != baseline_winner
            if changed:
                reversing.add(criterion.id)
            samples.append(
                SensitivitySample(
                    criterion_id=criterion.id,
                    varied_weight=varied_weight,
                    winner_option_id=winner,
                    winner_changed=changed,
                )
            )
    return SensitivityResult(
        baseline_winner_option_id=baseline_winner,
        stability=StabilityLabel.SENSITIVE if reversing else StabilityLabel.STABLE,
        reversing_criterion_ids=sorted(reversing),
        samples=samples,
    )


def _sample_weights(weight: Decimal, range_percent: Decimal, sample_count: int) -> list[Decimal]:
    minimum = max(ZERO, weight * (ONE - range_percent))
    maximum = min(ONE, weight * (ONE + range_percent))
    if sample_count == 1 or minimum == maximum:
        return [weight]
    step = (maximum - minimum) / Decimal(sample_count - 1)
    values = [minimum + step * index for index in range(sample_count)]
    return list(dict.fromkeys([*values, weight]))


def _rebalance_weights(
    weights: dict[str, Decimal],
    target: DecisionCriterion,
    varied_weight: Decimal,
) -> dict[str, Decimal]:
    remaining_ids = [criterion_id for criterion_id, weight in weights.items() if criterion_id != target.id and weight > ZERO]
    remaining_total = sum((weights[criterion_id] for criterion_id in remaining_ids), ZERO)
    if remaining_total == ZERO:
        return {criterion_id: ONE if criterion_id == target.id else ZERO for criterion_id in weights}
    scale = (ONE - varied_weight) / remaining_total
    return {
        criterion_id: (
            varied_weight
            if criterion_id == target.id
            else weights[criterion_id] * scale
            if criterion_id in remaining_ids
            else ZERO
        )
        for criterion_id in weights
    }


def _coverage(request: DecisionAnalysisRequest) -> EvidenceCoverage:
    provenance_counts = defaultdict(int)
    complete_criteria: set[str] = set()
    for score in request.scores:
        provenance_counts[score.provenance] += 1
    for criterion in request.criteria:
        values = [
            score
            for score in request.scores
            if score.criterion_id == criterion.id
        ]
        if all(score.provenance == ScoreProvenance.EVIDENCE_BACKED for score in values):
            complete_criteria.add(criterion.id)
    return EvidenceCoverage(
        input_complete=True,
        evidence_backed_weight=sum(
            (
                criterion.weight
                for criterion in request.criteria
                if criterion.id in complete_criteria
            ),
            ZERO,
        ),
        user_provided_score_count=provenance_counts[ScoreProvenance.USER_PROVIDED],
        evidence_backed_score_count=provenance_counts[ScoreProvenance.EVIDENCE_BACKED],
        derived_score_count=provenance_counts[ScoreProvenance.DERIVED],
    )


def _warnings(
    breakdowns: list[CriterionBreakdown], coverage: EvidenceCoverage
) -> list[str]:
    warnings = [
        f"criterion {breakdown.criterion_id} has equal values and does not distinguish options"
        for breakdown in breakdowns
        if breakdown.equal_values
    ]
    if coverage.user_provided_score_count:
        warnings.append("user-provided scores affect the ranking")
    if coverage.derived_score_count:
        warnings.append("derived scores affect the ranking")
    return warnings
