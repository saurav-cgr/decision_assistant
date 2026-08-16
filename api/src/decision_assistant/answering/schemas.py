from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerState(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    CONFLICTED = "conflicted"
    ABSTAINED = "abstained"


class ConfidenceCategory(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Citation(AnswerModel):
    passage_id: UUID
    quote: Annotated[str, Field(min_length=1)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(gt=0)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def offsets_match_quote_length(self) -> "Citation":
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        if self.end_offset - self.start_offset != len(self.quote):
            raise ValueError("citation offsets must span the quote length")
        return self


class CitationCandidate(AnswerModel):
    passage_id: UUID
    quote: Annotated[str, Field(min_length=1)]


class SourceCitation(Citation):
    document_id: UUID
    document_name: str
    locator: dict[str, Any]


class AnswerClaim(AnswerModel):
    text: Annotated[str, Field(min_length=1)]
    central: bool = False
    passage_ids: list[UUID] = Field(default_factory=list)
    explicit_entities: list[str] = Field(default_factory=list)
    explicit_dates: list[str] = Field(default_factory=list)


class EvidenceConflict(AnswerModel):
    facet: Annotated[str, Field(min_length=1)]
    passage_ids: Annotated[list[UUID], Field(min_length=2)]

    @field_validator("passage_ids")
    @classmethod
    def passage_ids_must_be_distinct(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("conflict passage_ids must be distinct")
        return value


class EvidencePassage(AnswerModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id: UUID
    content: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    active_version: bool

    @model_validator(mode="after")
    def content_hash_matches_content(self) -> "EvidencePassage":
        actual = sha256(self.content.encode()).hexdigest()
        if self.content_hash != actual:
            raise ValueError("content_hash does not match passage content")
        return self


class DecisionFieldEvidence(AnswerModel):
    decision_id: UUID
    field_name: Annotated[str, Field(min_length=1)]
    value: Annotated[str, Field(min_length=1)]
    passage_id: UUID
    provenance: Literal["extracted", "user_corrected"]
    support_state: Literal["supported", "unsupported", "needs_review"]


class EvidencePack(AnswerModel):
    passages: list[EvidencePassage] = Field(default_factory=list)
    decision_fields: list[DecisionFieldEvidence] = Field(default_factory=list)


class GeneratedAnswer(AnswerModel):
    answer: Annotated[str, Field(min_length=1)]
    claims: list[AnswerClaim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)
    confidence: ConfidenceCategory


class GeneratedAnswerCandidate(AnswerModel):
    answer: Annotated[str, Field(min_length=1)]
    claims: list[AnswerClaim] = Field(default_factory=list)
    citations: list[CitationCandidate] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)
    confidence: ConfidenceCategory


class VerificationError(AnswerModel):
    code: str
    message: str
    passage_id: UUID | None = None


class VerificationResult(AnswerModel):
    valid: bool
    state: AnswerState
    errors: list[VerificationError] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)


class QuestionRequest(AnswerModel):
    question: Annotated[str, Field(min_length=1, max_length=2_000)]

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class QuestionResponse(AnswerModel):
    answer: str
    state: AnswerState
    confidence: ConfidenceCategory
    claims: list[AnswerClaim] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)
    trace_id: UUID
