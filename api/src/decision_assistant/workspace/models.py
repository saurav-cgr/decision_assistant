from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base, TimestampMixin


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_workspaces_status",
        ),
        Index(
            "uq_workspaces_one_active_per_owner",
            "owner_user_id",
            "is_active",
            unique=True,
            postgresql_where=text("is_active = true AND owner_user_id IS NOT NULL"),
        ),
        UniqueConstraint("owner_user_id", "name", name="uq_workspaces_owner_name"),
        CheckConstraint(
            "knowledge_revision >= 1",
            name="ck_workspaces_knowledge_revision_positive",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(CITEXT)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    embedding_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    knowledge_revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    disclosure_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
