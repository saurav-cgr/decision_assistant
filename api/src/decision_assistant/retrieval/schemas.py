from datetime import date, datetime
from typing import Any, Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetrievalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetrievalFilters(RetrievalModel):
    person: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    project: str | None = None
    document_type: str | None = None


class RetrievalSearchRequest(RetrievalModel):
    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class RetrievalResult(RetrievalModel):
    passage_id: UUID
    content: str
    locator: dict[str, Any]
    fused_score: float
    source_ranks: dict[str, int]


class RetrievalSearchResponse(RetrievalModel):
    trace_id: UUID
    results: list[RetrievalResult]


class RetrievalTraceResponse(RetrievalModel):
    id: UUID
    request_id: str
    normalized_question: str
    filters: dict[str, Any]
    semantic_candidates: list[dict[str, Any]]
    keyword_candidates: list[dict[str, Any]]
    decision_candidates: list[dict[str, Any]]
    fused_results: list[dict[str, Any]]
    selected_passage_ids: list[str]
    timings: dict[str, Any]
    configuration: dict[str, Any]
    created_at: datetime
