from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base, TimestampMixin


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_workspace_updated",
            "workspace_id",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    title: Mapped[str] = mapped_column(String(200))


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "turn_number",
            name="uq_conversation_messages_turn",
        ),
        CheckConstraint(
            "turn_number >= 1",
            name="ck_conversation_messages_turn_number_positive",
        ),
        CheckConstraint(
            "response_schema_version >= 1",
            name="ck_conversation_messages_response_schema_version_positive",
        ),
        CheckConstraint(
            "knowledge_revision >= 1",
            name="ck_conversation_messages_knowledge_revision_positive",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
    )
    trace_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_traces.id", ondelete="CASCADE"),
    )
    turn_number: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response_schema_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
    )
    knowledge_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
