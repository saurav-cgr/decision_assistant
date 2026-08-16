from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base


class QuestionAnswer(Base):
    __tablename__ = "question_answers"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "normalized_question",
            name="uq_question_answers_workspace_normalized_question",
        ),
        CheckConstraint(
            "response_schema_version >= 1",
            name="ck_question_answers_response_schema_version_positive",
        ),
        CheckConstraint(
            "knowledge_revision >= 1",
            name="ck_question_answers_knowledge_revision_positive",
        ),
        Index(
            "ix_question_answers_workspace_last_asked",
            "workspace_id",
            "last_asked_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    trace_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_traces.id", ondelete="CASCADE"),
    )
    question: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[str] = mapped_column(Text)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response_schema_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
    )
    knowledge_revision: Mapped[int] = mapped_column(Integer)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    last_asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
