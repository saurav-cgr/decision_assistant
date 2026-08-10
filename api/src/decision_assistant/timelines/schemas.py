from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from decision_assistant.decisions.schemas import (
    DecisionRelationType,
    DecisionStatus,
    RelationConfidence,
)


class TimelineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimelineEvidence(TimelineModel):
    passage_id: UUID
    document_id: UUID
    document_version_id: UUID
    quote: str
    start_offset: int
    end_offset: int
    content_hash: str
    locator: dict[str, object]


class TimelineRelationship(TimelineModel):
    source_decision_id: UUID
    target_decision_id: UUID
    relation_type: DecisionRelationType
    label: Literal[
        "supersedes",
        "revises",
        "relates_to",
        "possible_revision",
    ]
    authority: Literal["model_inferred", "user_confirmed"]
    confidence: RelationConfidence | None
    rationale: str | None


class TimelineEntry(TimelineModel):
    decision_id: UUID
    statement: str
    effective_date: date | None
    display_date: date | None
    date_is_fallback: bool
    original_status: DecisionStatus
    display_status: DecisionStatus
    owner: str | None
    project: str | None
    topic: str | None
    provenance: Literal["extracted", "user_corrected"]
    evidence: list[TimelineEvidence]
    relationships: list[TimelineRelationship]


class TimelineResponse(TimelineModel):
    topic: str
    entries: list[TimelineEntry]
