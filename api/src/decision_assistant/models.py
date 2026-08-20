from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import (
    CITEXT,
    JSONB,
    TSVECTOR,
    UUID as PGUUID,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIMENSION = 768


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    recovery_code_id: Mapped[UUID] = mapped_column(
        default=uuid4,
        unique=True,
    )
    recovery_code_hash: Mapped[str] = mapped_column(Text)
    token_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
    )


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
    embedding_profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
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


from decision_assistant.evaluation.models import (  # noqa: E402, F401
    EvaluationQuestion,
    EvaluationResult,
    EvaluationRun,
)
