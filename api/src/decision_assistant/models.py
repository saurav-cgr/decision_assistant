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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PGUUID
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


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    embedding_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


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
    request_id: Mapped[str] = mapped_column(String(100), index=True)
    normalized_question: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    semantic_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    keyword_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    decision_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    fused_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    selected_passage_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    timings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class EvaluationQuestion(TimestampMixin, Base):
    __tablename__ = "evaluation_questions"
    __table_args__ = (
        CheckConstraint(
            "expectation IN ('answer', 'abstain', 'partial')",
            name="ck_evaluation_questions_expectation",
        ),
        UniqueConstraint(
            "dataset_version",
            "external_id",
            name="uq_evaluation_questions_dataset_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100))
    dataset_version: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(Text)
    expected_answer_summary: Mapped[str | None] = mapped_column(Text)
    expected_documents: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    expected_passages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    expected_status: Mapped[str | None] = mapped_column(String(30))
    expectation: Mapped[str] = mapped_column(String(20))
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)


class EvaluationRun(TimestampMixin, Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ('semantic', 'hybrid')",
            name="ck_evaluation_runs_strategy",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_evaluation_runs_status",
        ),
        CheckConstraint(
            "completed_questions >= 0 AND total_questions >= 0 "
            "AND completed_questions <= total_questions",
            name="ck_evaluation_runs_progress",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    completed_questions: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    failure: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dataset_version: Mapped[str] = mapped_column(String(100))
    generation_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    judge_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    aggregate_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "evaluation_question_id",
            name="uq_evaluation_results_run_question",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    evaluation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        index=True,
    )
    evaluation_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_questions.id", ondelete="CASCADE"),
        index=True,
    )
    retrieval_trace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("retrieval_traces.id", ondelete="SET NULL"),
        nullable=True,
    )
    retrieved_ranks: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    generated_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    citation_checks: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    expected_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    actual_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    judge_prompt: Mapped[str | None] = mapped_column(Text)
    judge_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    judge_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
