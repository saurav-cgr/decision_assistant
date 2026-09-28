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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base, TimestampMixin


class CorpusRebuild(TimestampMixin, Base):
    """Tracks an in-progress or completed corpus rebuild for a workspace.

    Per data-model.md / T007's migration (0012_production_readiness): at most one
    active (`pending`/`running`) rebuild per workspace, enforced by a partial
    unique index.
    """

    __tablename__ = "corpus_rebuilds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_corpus_rebuilds_status",
        ),
        Index(
            "uq_corpus_rebuilds_one_active_per_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    documents_total: Mapped[int] = mapped_column(Integer, nullable=False)
    documents_completed: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
