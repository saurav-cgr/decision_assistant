from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base, TimestampMixin

EMBEDDING_DIMENSION = 768


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(150))
    active_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_documents_active_version_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_number",
        ),
        CheckConstraint(
            "state IN ('staging', 'active', 'retired', 'failed')",
            name="ck_document_versions_state",
        ),
        Index(
            "uq_document_versions_one_active",
            "document_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(500))
    document_date: Mapped[date | None] = mapped_column(Date)
    participants: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    source_type: Mapped[str | None] = mapped_column(String(100))
    project: Mapped[str | None] = mapped_column(String(300))
    checksum: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str | None] = mapped_column(Text)
    chunking_profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    state: Mapped[str] = mapped_column(String(20), default="staging")
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmbeddingCache(TimestampMixin, Base):
    __tablename__ = "embedding_cache"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "content_hash",
            "embedding_profile_fingerprint",
            name="uq_embedding_cache_content_profile",
        ),
        Index(
            "ix_embedding_cache_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_profile_fingerprint: Mapped[str] = mapped_column(String(64))
    embedding_profile: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Deprecated duplicate; semantic retrieval uses EmbeddingCache.embedding.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION), nullable=True
    )


class Passage(TimestampMixin, Base):
    __tablename__ = "passages"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "sequence_number",
            name="uq_passages_version_sequence",
        ),
        CheckConstraint("start_offset >= 0", name="ck_passages_start_offset"),
        CheckConstraint("end_offset >= start_offset", name="ck_passages_end_offset"),
        CheckConstraint(
            "retrieval_unit_kind IN ('passage', 'parent', 'sentence')",
            name="ck_passages_retrieval_unit_kind",
        ),
        CheckConstraint(
            "(retrieval_unit_kind = 'sentence' AND parent_passage_id IS NOT NULL) "
            "OR (retrieval_unit_kind <> 'sentence' AND parent_passage_id IS NULL)",
            name="ck_passages_parent_unit_link",
        ),
        Index("ix_passages_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_passages_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english'::regconfig, content)", persisted=True),
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
    # Embedding-only; chunking metadata lives on DocumentVersion.chunking_profile.
    # Non-null: this schema generation has no legacy migratable rows.
    # Deprecated duplicate; profile identity lives on EmbeddingCache.
    embedding_profile: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # Structural context of the passage's units (shared group_path and sorted
    # unique block_types). Historic rows carry the '{}' default until the
    # approved corpus reset and reingestion replace them.
    structural_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    embedding_cache_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("embedding_cache.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    retrieval_unit_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="passage",
        server_default=text("'passage'"),
    )
    parent_passage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("passages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


class IngestionJob(TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ingestion_jobs_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_ingestion_jobs_progress"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    stage: Mapped[str] = mapped_column(String(50), default="pending")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str] = mapped_column(String(100), index=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
