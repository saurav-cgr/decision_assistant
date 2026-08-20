from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base, TimestampMixin


class EvaluationQuestion(TimestampMixin, Base):
    __tablename__ = "evaluation_questions"
    __table_args__ = (
        CheckConstraint(
            "expectation IN ('answer', 'abstain', 'partial')",
            name="ck_evaluation_questions_expectation",
        ),
        UniqueConstraint(
            "workspace_id",
            "dataset_version",
            "external_id",
            name="uq_evaluation_questions_workspace_dataset_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(100))
    dataset_version: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(Text)
    expected_answer_summary: Mapped[str | None] = mapped_column(Text)
    expected_documents: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list
    )
    expected_passages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list
    )
    expected_status: Mapped[str | None] = mapped_column(String(30))
    expectation: Mapped[str] = mapped_column(String(20))
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)


class EvaluationRun(TimestampMixin, Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ("
            "'semantic', 'hybrid', 'passage_hybrid', "
            "'sentence_expanded', 'parent_child_merged'"
            ")",
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
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
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
    corpus_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
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
    answer_diagnostics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
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
