from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecisionAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionDirection(StrEnum):
    BENEFIT = "benefit"
    COST = "cost"


class CriterionScale(StrEnum):
    NUMERIC = "numeric"
    ORDINAL = "ordinal"


class ScoreProvenance(StrEnum):
    USER_PROVIDED = "user_provided"
    EVIDENCE_BACKED = "evidence_backed"
    DERIVED = "derived"


class StabilityLabel(StrEnum):
    STABLE = "stable"
    SENSITIVE = "sensitive"
    INDETERMINATE = "indeterminate"


class NarrativeStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    GENERATED = "generated"
    UNAVAILABLE = "unavailable"


class DecisionOption(DecisionAnalysisModel):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=2_000)] | None = None


class DecisionCriterion(DecisionAnalysisModel):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    direction: CriterionDirection
    weight: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=8)]
    scale: CriterionScale


class ScoreCitation(DecisionAnalysisModel):
    passage_id: UUID
    quote: Annotated[str, Field(min_length=1, max_length=2_000)]


class ScoreInput(DecisionAnalysisModel):
    option_id: Annotated[str, Field(min_length=1, max_length=80)]
    criterion_id: Annotated[str, Field(min_length=1, max_length=80)]
    value: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=8)]
    provenance: ScoreProvenance
    rationale: Annotated[str, Field(max_length=2_000)] | None = None
    citations: list[ScoreCitation] = Field(default_factory=list)

    @model_validator(mode="after")
    def citation_rules_match_provenance(self) -> "ScoreInput":
        if self.provenance == ScoreProvenance.EVIDENCE_BACKED and not self.citations:
            raise ValueError("evidence_backed scores require at least one citation")
        if self.provenance != ScoreProvenance.EVIDENCE_BACKED and self.citations:
            raise ValueError("only evidence_backed scores may include citations")
        return self


class SensitivityRequest(DecisionAnalysisModel):
    range_percent: Annotated[Decimal, Field(gt=0, le=1, max_digits=4, decimal_places=3)] = Decimal("0.2")
    sample_count: Annotated[int, Field(ge=3, le=21)] = 5


class DecisionAnalysisRequest(DecisionAnalysisModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    options: Annotated[list[DecisionOption], Field(min_length=2, max_length=20)]
    criteria: Annotated[list[DecisionCriterion], Field(min_length=1, max_length=12)]
    scores: list[ScoreInput]
    sensitivity: SensitivityRequest | None = None
    narrative_requested: bool = False

    @model_validator(mode="after")
    def validate_decision_model(self) -> "DecisionAnalysisRequest":
        option_ids = [option.id for option in self.options]
        criterion_ids = [criterion.id for criterion in self.criteria]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("option IDs must be unique")
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("criterion IDs must be unique")

        total_weight = sum((criterion.weight for criterion in self.criteria), Decimal())
        if total_weight != Decimal("1"):
            raise ValueError("criterion weights must sum exactly to 1.0")
        if not any(criterion.weight > 0 for criterion in self.criteria):
            raise ValueError("at least one criterion weight must be positive")

        expected_pairs = {
            (option_id, criterion_id)
            for option_id in option_ids
            for criterion_id in criterion_ids
        }
        actual_pairs = {(score.option_id, score.criterion_id) for score in self.scores}
        if len(actual_pairs) != len(self.scores):
            raise ValueError("each option and criterion score pair must be unique")
        unknown_pairs = actual_pairs - expected_pairs
        if unknown_pairs:
            raise ValueError("scores must reference declared options and criteria")
        if actual_pairs != expected_pairs:
            raise ValueError("every option and criterion score pair is required")
        return self


class ScoreContribution(DecisionAnalysisModel):
    criterion_id: str
    raw_value: Decimal
    normalized_value: Decimal
    weighted_contribution: Decimal
    provenance: ScoreProvenance


class RankedOption(DecisionAnalysisModel):
    option_id: str
    rank: int
    total_score: Decimal
    contributions: list[ScoreContribution]


class CriterionValue(DecisionAnalysisModel):
    option_id: str
    raw_value: Decimal
    normalized_value: Decimal
    provenance: ScoreProvenance


class CriterionBreakdown(DecisionAnalysisModel):
    criterion_id: str
    weight: Decimal
    direction: CriterionDirection
    values: list[CriterionValue]
    equal_values: bool


class SensitivitySample(DecisionAnalysisModel):
    criterion_id: str
    varied_weight: Decimal
    winner_option_id: str
    winner_changed: bool


class SensitivityResult(DecisionAnalysisModel):
    baseline_winner_option_id: str
    stability: StabilityLabel
    reversing_criterion_ids: list[str] = Field(default_factory=list)
    samples: list[SensitivitySample] = Field(default_factory=list)


class EvidenceCoverage(DecisionAnalysisModel):
    input_complete: bool
    evidence_backed_weight: Decimal
    user_provided_score_count: int
    evidence_backed_score_count: int
    derived_score_count: int


class DecisionVerification(DecisionAnalysisModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GeneratedDecisionNarrative(DecisionAnalysisModel):
    recommendation_option_id: str
    summary: Annotated[str, Field(min_length=1, max_length=2_000)]
    dominant_criterion_ids: list[str] = Field(default_factory=list)
    tradeoffs: list[Annotated[str, Field(min_length=1, max_length=1_000)]] = (
        Field(default_factory=list)
    )
    assumptions: list[Annotated[str, Field(min_length=1, max_length=1_000)]] = (
        Field(default_factory=list)
    )


class DecisionAnalysisResponse(DecisionAnalysisModel):
    algorithm_version: str = "weighted-sum-v1"
    ranked_options: list[RankedOption]
    tie_groups: list[list[str]] = Field(default_factory=list)
    criterion_breakdowns: list[CriterionBreakdown]
    sensitivity: SensitivityResult | None = None
    evidence_coverage: EvidenceCoverage
    verification: DecisionVerification
    narrative: GeneratedDecisionNarrative | None = None
    narrative_status: NarrativeStatus = NarrativeStatus.NOT_REQUESTED
