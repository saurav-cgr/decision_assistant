from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base, TimestampMixin


class Decision(TimestampMixin, Base):
    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'proposed', 'rejected', 'superseded')",
            name="ck_decisions_status",
        ),
        CheckConstraint(
            "provenance IN ('extracted', 'user_corrected')",
            name="ck_decisions_provenance",
        ),
        CheckConstraint(
            "review_state IN ('supported', 'unsupported', 'needs_review')",
            name="ck_decisions_review_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        index=True,
    )
    statement: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    owner: Mapped[str | None] = mapped_column(String(300), index=True)
    status: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    alternatives: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    project: Mapped[str | None] = mapped_column(String(300), index=True)
    topic: Mapped[str | None] = mapped_column(String(300), index=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[str] = mapped_column(String(30), default="extracted")
    review_state: Mapped[str] = mapped_column(String(30), default="supported")
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    retired: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class DecisionEvidence(Base):
    __tablename__ = "decision_evidence"
    __table_args__ = (
        CheckConstraint(
            "support_state IN ('supported', 'unsupported', 'needs_review')",
            name="ck_decision_evidence_support_state",
        ),
        CheckConstraint("start_offset >= 0", name="ck_decision_evidence_start_offset"),
        CheckConstraint(
            "end_offset >= start_offset",
            name="ck_decision_evidence_end_offset",
        ),
        UniqueConstraint(
            "decision_id",
            "passage_id",
            "field_name",
            "start_offset",
            "end_offset",
            name="uq_decision_evidence_span",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"),
        index=True,
    )
    passage_id: Mapped[UUID] = mapped_column(
        ForeignKey("passages.id", ondelete="CASCADE"),
        index=True,
    )
    field_name: Mapped[str | None] = mapped_column(String(100))
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    support_state: Mapped[str] = mapped_column(String(30), default="supported")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64))
    citation_stale: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DecisionRelation(TimestampMixin, Base):
    __tablename__ = "decision_relations"
    __table_args__ = (
        CheckConstraint(
            "relation_type IN ('supersedes', 'revises', 'relates_to')",
            name="ck_decision_relations_type",
        ),
        CheckConstraint(
            "authority IN ('model_inferred', 'user_confirmed')",
            name="ck_decision_relations_authority",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
            name="ck_decision_relations_confidence",
        ),
        CheckConstraint(
            "source_decision_id <> target_decision_id",
            name="ck_decision_relations_not_self",
        ),
        UniqueConstraint(
            "source_decision_id",
            "target_decision_id",
            "relation_type",
            name="uq_decision_relations_edge",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"),
        index=True,
    )
    target_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"),
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(30))
    authority: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[str | None] = mapped_column(String(20))
    rationale: Mapped[str | None] = mapped_column(Text)


class DecisionRevision(Base):
    __tablename__ = "decision_revisions"
    __table_args__ = (
        CheckConstraint(
            "support_state IN ('supported', 'unsupported', 'needs_review')",
            name="ck_decision_revisions_support_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"),
        index=True,
    )
    field_name: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[Any | None] = mapped_column(JSONB)
    new_value: Mapped[Any | None] = mapped_column(JSONB)
    evidence_passage_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        default=list,
        server_default=text("'{}'"),
    )
    support_state: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
