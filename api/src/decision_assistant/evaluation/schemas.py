from datetime import datetime
from typing import Any, Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationDatasetQuestion(EvaluationModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    external_id: Annotated[str, Field(alias="id", min_length=1)]
    question: Annotated[str, Field(min_length=1)]
    expected_answer_summary: str | None = None
    expected_claims: list[dict[str, Any]] = Field(default_factory=list)
    expected_documents: list[dict[str, Any]] = Field(default_factory=list)
    expected_passages: list[dict[str, Any]] = Field(default_factory=list)
    expected_status: str | None = None
    expectation: Literal["answer", "abstain", "partial"]
    facets: dict[str, Literal["answer", "abstain", "partial"]] = Field(
        default_factory=dict
    )
    tags: list[str] = Field(default_factory=list)


class EvaluationDataset(EvaluationModel):
    version: Annotated[str, Field(min_length=1)]
    questions: list[EvaluationDatasetQuestion]

    @model_validator(mode="after")
    def question_ids_must_be_unique(self) -> "EvaluationDataset":
        ids = [question.external_id for question in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("evaluation question IDs must be unique")
        return self


class EvaluationRunRequest(EvaluationModel):
    strategy: Literal["semantic", "hybrid"]
    dataset_version: Annotated[str, Field(min_length=1)]
    configuration: dict[str, Any] = Field(default_factory=dict)
    generation_profile: dict[str, Any] = Field(default_factory=dict)
    embedding_profile: dict[str, Any] = Field(default_factory=dict)
    judge_profile: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def judge_must_use_zero_temperature(self) -> "EvaluationRunRequest":
        temperature = self.judge_profile.get("temperature", 0)
        if temperature != 0 and temperature != 0.0:
            raise ValueError("evaluation judge temperature must be zero")
        return self


class CitationAssessment(EvaluationModel):
    claim_index: Annotated[int, Field(ge=0)]
    passage_id: Annotated[str, Field(min_length=1)]
    supported: bool
    reason: Annotated[str, Field(min_length=1)]


class ClaimAssessment(EvaluationModel):
    claim_index: Annotated[int, Field(ge=0)]
    supported: bool
    reason: str | None = None


class ClaimJudgeOutput(EvaluationModel):
    claims: list[ClaimAssessment] = Field(default_factory=list)
    citation_assessments: list[CitationAssessment] = Field(default_factory=list)
    facet_outcomes: dict[
        str, Literal["answer", "abstain", "partial"]
    ] = Field(default_factory=dict)
    supported_claims: int = 0
    total_claims: int = 0


class EvaluationResultResponse(EvaluationModel):
    id: UUID
    question_id: UUID
    external_id: str
    retrieved_ranks: dict[str, Any]
    generated_output: dict[str, Any] | None
    answer_diagnostics: dict[str, Any] | None = None
    citation_checks: dict[str, Any]
    expected_values: dict[str, Any]
    actual_values: dict[str, Any]
    latency_ms: float | None
    judge_prompt: str | None
    judge_profile: dict[str, Any] | None
    judge_output: dict[str, Any] | None
    failure_reason: str | None


class EvaluationRunResponse(EvaluationModel):
    id: UUID
    strategy: Literal["semantic", "hybrid"]
    status: Literal["pending", "running", "completed", "failed"]
    completed_questions: int
    total_questions: int
    failure: dict[str, Any] | None
    configuration: dict[str, Any]
    dataset_version: str
    generation_profile: dict[str, Any]
    embedding_profile: dict[str, Any]
    judge_profile: dict[str, Any]
    corpus_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    aggregate_metrics: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None
    results: list[EvaluationResultResponse] = Field(default_factory=list)


class EvaluationRunSummaryResponse(EvaluationModel):
    """Lightweight run metadata without per-question results."""

    id: UUID
    strategy: Literal["semantic", "hybrid"]
    status: Literal["pending", "running", "completed", "failed"]
    completed_questions: int
    total_questions: int
    failure: dict[str, Any] | None
    dataset_version: str
    aggregate_metrics: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
