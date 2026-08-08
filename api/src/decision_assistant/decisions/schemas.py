from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Annotated
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
