from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from decision_assistant.decision_analysis.schemas import (
    CriterionDirection,
    CriterionScale,
    DecisionAnalysisRequest,
    DecisionCriterion,
    DecisionOption,
    ScoreInput,
    ScoreProvenance,
    SensitivityRequest,
)
from decision_assistant.decision_analysis.scoring import calculate_decision
from decision_assistant.decision_analysis.verifier import DecisionAnalysisVerifier


def request_for(
    *,
    cost_weight: str = "0.4",
    quality_weight: str = "0.6",
    sensitivity: SensitivityRequest | None = None,
) -> DecisionAnalysisRequest:
    return DecisionAnalysisRequest(
        title="Choose deployment",
        options=[
            DecisionOption(id="managed", label="Managed"),
            DecisionOption(id="self_hosted", label="Self-hosted"),
        ],
        criteria=[
            DecisionCriterion(
                id="cost",
                label="Monthly cost",
                direction=CriterionDirection.COST,
                weight=Decimal(cost_weight),
                scale=CriterionScale.NUMERIC,
            ),
            DecisionCriterion(
                id="quality",
                label="Quality",
                direction=CriterionDirection.BENEFIT,
                weight=Decimal(quality_weight),
                scale=CriterionScale.ORDINAL,
            ),
        ],
        scores=[
            ScoreInput(
                option_id="managed",
                criterion_id="cost",
                value=Decimal("100"),
                provenance=ScoreProvenance.USER_PROVIDED,
            ),
            ScoreInput(
                option_id="managed",
                criterion_id="quality",
                value=Decimal("8"),
                provenance=ScoreProvenance.USER_PROVIDED,
            ),
            ScoreInput(
                option_id="self_hosted",
                criterion_id="cost",
                value=Decimal("40"),
                provenance=ScoreProvenance.USER_PROVIDED,
            ),
            ScoreInput(
                option_id="self_hosted",
                criterion_id="quality",
                value=Decimal("6"),
                provenance=ScoreProvenance.USER_PROVIDED,
            ),
        ],
        sensitivity=sensitivity,
    )


def test_calculates_benefit_and_cost_criteria_with_decimal_totals() -> None:
    response = calculate_decision(request_for())

    assert [item.option_id for item in response.ranked_options] == [
        "managed",
        "self_hosted",
    ]
    assert response.ranked_options[0].total_score == Decimal("0.6")
    assert response.ranked_options[1].total_score == Decimal("0.4")
    assert response.ranked_options[0].rank == 1
    assert response.criterion_breakdowns[0].values[0].normalized_value == Decimal("0")
    assert response.criterion_breakdowns[0].values[1].normalized_value == Decimal("1")
    assert response.criterion_breakdowns[1].values[0].normalized_value == Decimal("1")


def test_stable_request_order_breaks_ties_and_exposes_tie_group() -> None:
    request = request_for(cost_weight="0.5", quality_weight="0.5")
    response = calculate_decision(request)

    assert [item.option_id for item in response.ranked_options] == [
        "managed",
        "self_hosted",
    ]
    assert response.tie_groups == [["managed", "self_hosted"]]


def test_equal_criterion_values_do_not_create_false_distinction() -> None:
    request = request_for()
    request = request.model_copy(
        update={
            "scores": [
                score.model_copy(update={"value": Decimal("9")})
                if score.criterion_id == "quality"
                else score
                for score in request.scores
            ]
        }
    )

    response = calculate_decision(request)

    quality = response.criterion_breakdowns[1]
    assert quality.equal_values is True
    assert [value.normalized_value for value in quality.values] == [
        Decimal("1"),
        Decimal("1"),
    ]
    assert "criterion quality has equal values and does not distinguish options" in response.verification.warnings


def test_rejects_missing_or_duplicate_score_pairs() -> None:
    request = request_for()

    with pytest.raises(ValidationError, match="every option and criterion score pair"):
        DecisionAnalysisRequest(**request.model_dump(exclude={"scores"}), scores=request.scores[:-1])
    with pytest.raises(ValidationError, match="each option and criterion score pair"):
        DecisionAnalysisRequest(**request.model_dump(exclude={"scores"}), scores=[*request.scores, request.scores[0]])


def test_rejects_non_unit_weights() -> None:
    with pytest.raises(ValidationError, match="weights must sum exactly"):
        request_for(cost_weight="0.3", quality_weight="0.6")


def test_evidence_backed_scores_require_citations() -> None:
    with pytest.raises(ValidationError, match="require at least one citation"):
        ScoreInput(
            option_id="managed",
            criterion_id="quality",
            value=Decimal("8"),
            provenance=ScoreProvenance.EVIDENCE_BACKED,
        )
    cited = ScoreInput(
        option_id="managed",
        criterion_id="quality",
        value=Decimal("8"),
        provenance=ScoreProvenance.EVIDENCE_BACKED,
        citations=[{"passage_id": uuid4(), "quote": "Measured quality: 8"}],
    )
    assert cited.citations


def test_sensitivity_flags_rank_reversal() -> None:
    response = calculate_decision(
        request_for(sensitivity=SensitivityRequest(range_percent=Decimal("0.5"), sample_count=3))
    )

    assert response.sensitivity is not None
    assert response.sensitivity.stability == "sensitive"
    assert response.sensitivity.reversing_criterion_ids == ["cost", "quality"]
    assert any(sample.winner_changed for sample in response.sensitivity.samples)


def test_verifier_checks_response_totals() -> None:
    request = request_for()
    response = calculate_decision(request)
    invalid = response.model_copy(
        update={
            "ranked_options": [
                response.ranked_options[0].model_copy(update={"total_score": Decimal("9")}),
                response.ranked_options[1],
            ]
        }
    )

    verification = DecisionAnalysisVerifier().verify(request, invalid)

    assert verification.valid is False
    assert verification.errors == ["total score mismatch for option managed"]
