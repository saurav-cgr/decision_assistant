from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionStatus(StrEnum):
    ACTIVE = "active"
    PROPOSED = "proposed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class DecisionRelationType(StrEnum):
    SUPERSEDES = "supersedes"
    REVISES = "revises"
    RELATES_TO = "relates_to"


class RelationConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExtractionPassage(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id: UUID
    content: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_content_hash(self) -> "ExtractionPassage":
        actual = sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_hash != actual:
            raise ValueError("content_hash does not match passage content")
        return self


class EvidenceQuote(StrictModel):
    passage_id: UUID
    quote: Annotated[str, Field(min_length=1)]


class DecisionRelationCandidate(StrictModel):
    target_decision_id: UUID
    relation_type: DecisionRelationType
    confidence: RelationConfidence
    rationale: str | None = None


class DecisionCandidate(StrictModel):
    statement: Annotated[str, Field(min_length=1)]
    effective_date: date | None = None
    owner: str | None = None
    status: DecisionStatus
    reasons: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    project: str | None = None
    topic: str | None = None
    extraction_confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    evidence: EvidenceQuote
    relation: DecisionRelationCandidate | None = None


class DecisionExtractionResponse(StrictModel):
    decisions: list[DecisionCandidate] = Field(default_factory=list)


class AlignedEvidence(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id: UUID
    quote: str
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(gt=0)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ExtractedDecision(StrictModel):
    statement: str
    effective_date: date | None
    owner: str | None
    status: DecisionStatus
    reasons: list[str]
    alternatives: list[str]
    project: str | None
    topic: str | None
    extraction_confidence: float | None
    evidence: AlignedEvidence
    relation: DecisionRelationCandidate | None


DecisionFieldName = Literal[
    "statement",
    "effective_date",
    "owner",
    "status",
    "reasons",
    "alternatives",
    "project",
    "topic",
]
SupportState = Literal["supported", "unsupported", "needs_review"]


class EvidenceSelection(StrictModel):
    passage_id: UUID
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(gt=0)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "EvidenceSelection":
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class DecisionChange(StrictModel):
    field_name: DecisionFieldName
    value: Any
    support_state: Literal["supported", "unsupported"]
    evidence: list[EvidenceSelection] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_change(self) -> "DecisionChange":
        if self.support_state == "supported" and not self.evidence:
            raise ValueError("supported corrections require evidence")
        if self.support_state == "unsupported" and self.evidence:
            raise ValueError("unsupported corrections cannot cite evidence")

        value = self.value
        if self.field_name == "statement":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("statement must be a non-empty string")
        elif self.field_name == "effective_date":
            if isinstance(value, str):
                try:
                    value = date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("effective_date must be an ISO date") from exc
                object.__setattr__(self, "value", value)
            elif value is not None and not isinstance(value, date):
                raise ValueError("effective_date must be an ISO date or null")
        elif self.field_name in {"owner", "project", "topic"}:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{self.field_name} must be a string or null")
        elif self.field_name == "status":
            try:
                normalized = DecisionStatus(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("status is invalid") from exc
            object.__setattr__(self, "value", normalized.value)
        elif self.field_name in {"reasons", "alternatives"}:
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(f"{self.field_name} must be a list of strings")
        return self


class DecisionCorrectionRequest(StrictModel):
    changes: Annotated[list[DecisionChange], Field(min_length=1)]

    @model_validator(mode="after")
    def fields_must_be_distinct(self) -> "DecisionCorrectionRequest":
        fields = [change.field_name for change in self.changes]
        if len(set(fields)) != len(fields):
            raise ValueError("corrected fields must be distinct")
        return self


class DecisionEvidenceResponse(StrictModel):
    passage_id: UUID
    field_name: str | None
    quote: str
    start_offset: int
    end_offset: int
    content_hash: str
    support_state: SupportState
    is_primary: bool


class DecisionRevisionResponse(StrictModel):
    id: UUID
    field_name: str
    old_value: Any | None
    new_value: Any | None
    evidence_passage_ids: list[UUID]
    support_state: SupportState


class DecisionRelationRequest(StrictModel):
    target_decision_id: UUID
    relation_type: DecisionRelationType
    rationale: str | None = None


class DecisionRelationResponse(StrictModel):
    id: UUID
    source_decision_id: UUID
    target_decision_id: UUID
    relation_type: DecisionRelationType
    authority: Literal["model_inferred", "user_confirmed"]
    confidence: RelationConfidence | None
    rationale: str | None


class DecisionSummary(StrictModel):
    id: UUID
    document_version_id: UUID
    statement: str
    effective_date: date | None
    owner: str | None
    status: DecisionStatus
    reasons: list[str]
    alternatives: list[str]
    project: str | None
    topic: str | None
    extraction_confidence: float | None
    provenance: Literal["extracted", "user_corrected"]
    review_state: SupportState
    user_edited: bool
    retired: bool


class DecisionListResponse(StrictModel):
    items: list[DecisionSummary]


class DecisionDetail(DecisionSummary):
    evidence: list[DecisionEvidenceResponse]
    revisions: list[DecisionRevisionResponse]
    relations: list[DecisionRelationResponse]
