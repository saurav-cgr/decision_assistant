from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base


class RetrievalTrace(Base):
    __tablename__ = "retrieval_traces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    request_id: Mapped[str] = mapped_column(String(100), index=True)
    normalized_question: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    semantic_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    keyword_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    decision_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    fused_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    selected_passage_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    selected_passage_metadata: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    rerank: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
