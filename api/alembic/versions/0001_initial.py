"""Create the initial decision assistant schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")
EMPTY_ARRAY = sa.text("'[]'::jsonb")
EMPTY_OBJECT = sa.text("'{}'::jsonb")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "workspaces",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("embedding_profile", postgresql.JSONB(), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("name", name="uq_workspaces_name"),
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("display_name", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(150), nullable=False),
        sa.Column("active_version_id", UUID, nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])

    op.create_table(
        "document_versions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("participants", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("source_type", sa.String(100), nullable=True),
        sa.Column("project", sa.String(300), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=True),
        sa.Column("state", sa.String(20), server_default="staging", nullable=False),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_document_number"),
        sa.CheckConstraint(
            "state IN ('staging', 'active', 'retired', 'failed')",
            name="ck_document_versions_state",
        ),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index(
        "uq_document_versions_one_active",
        "document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_foreign_key(
        "fk_documents_active_version_id",
        "documents",
        "document_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "passages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("document_version_id", UUID, nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english'::regconfig, content)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", Vector(768), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_version_id", "sequence_number", name="uq_passages_version_sequence"),
        sa.CheckConstraint("start_offset >= 0", name="ck_passages_start_offset"),
        sa.CheckConstraint("end_offset >= start_offset", name="ck_passages_end_offset"),
    )
    op.create_index("ix_passages_document_version_id", "passages", ["document_version_id"])
    op.create_index("ix_passages_content_hash", "passages", ["content_hash"])
    op.create_index("ix_passages_search_vector", "passages", ["search_vector"], postgresql_using="gin")
    op.create_index(
        "ix_passages_embedding_hnsw",
        "passages",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "decisions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("document_version_id", UUID, nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("owner", sa.String(300), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("alternatives", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("project", sa.String(300), nullable=True),
        sa.Column("topic", sa.String(300), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("provenance", sa.String(30), server_default="extracted", nullable=False),
        sa.Column("review_state", sa.String(30), server_default="supported", nullable=False),
        sa.Column("user_edited", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("retired", sa.Boolean(), server_default=sa.false(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('active', 'proposed', 'rejected', 'superseded')", name="ck_decisions_status"),
        sa.CheckConstraint("provenance IN ('extracted', 'user_corrected')", name="ck_decisions_provenance"),
        sa.CheckConstraint("review_state IN ('supported', 'unsupported', 'needs_review')", name="ck_decisions_review_state"),
    )
    for column in ("document_version_id", "owner", "project", "topic", "retired"):
        op.create_index(f"ix_decisions_{column}", "decisions", [column])

    op.create_table(
        "decision_evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("decision_id", UUID, nullable=False),
        sa.Column("passage_id", UUID, nullable=False),
        sa.Column("field_name", sa.String(100), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("support_state", sa.String(30), server_default="supported", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passage_id"], ["passages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("decision_id", "passage_id", "field_name", "start_offset", "end_offset", name="uq_decision_evidence_span"),
        sa.CheckConstraint("support_state IN ('supported', 'unsupported', 'needs_review')", name="ck_decision_evidence_support_state"),
        sa.CheckConstraint("start_offset >= 0", name="ck_decision_evidence_start_offset"),
        sa.CheckConstraint("end_offset >= start_offset", name="ck_decision_evidence_end_offset"),
    )
    op.create_index("ix_decision_evidence_decision_id", "decision_evidence", ["decision_id"])
    op.create_index("ix_decision_evidence_passage_id", "decision_evidence", ["passage_id"])

    op.create_table(
        "decision_relations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("source_decision_id", UUID, nullable=False),
        sa.Column("target_decision_id", UUID, nullable=False),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("authority", sa.String(30), nullable=False),
        sa.Column("confidence", sa.String(20), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["source_decision_id"], ["decisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_decision_id"], ["decisions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_decision_id", "target_decision_id", "relation_type", name="uq_decision_relations_edge"),
        sa.CheckConstraint("relation_type IN ('supersedes', 'revises', 'relates_to')", name="ck_decision_relations_type"),
        sa.CheckConstraint("authority IN ('model_inferred', 'user_confirmed')", name="ck_decision_relations_authority"),
        sa.CheckConstraint("confidence IS NULL OR confidence IN ('low', 'medium', 'high')", name="ck_decision_relations_confidence"),
        sa.CheckConstraint("source_decision_id <> target_decision_id", name="ck_decision_relations_not_self"),
    )
    op.create_index("ix_decision_relations_source_decision_id", "decision_relations", ["source_decision_id"])
    op.create_index("ix_decision_relations_target_decision_id", "decision_relations", ["target_decision_id"])

    op.create_table(
        "decision_revisions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("decision_id", UUID, nullable=False),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_passage_ids", postgresql.ARRAY(UUID), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("support_state", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("support_state IN ('supported', 'unsupported', 'needs_review')", name="ck_decision_revisions_support_state"),
    )
    op.create_index("ix_decision_revisions_decision_id", "decision_revisions", ["decision_id"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("document_version_id", UUID, nullable=True),
        sa.Column("stage", sa.String(50), server_default="pending", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_ingestion_jobs_status"),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_ingestion_jobs_progress"),
    )
    for column in ("document_id", "status", "request_id"):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])

    op.create_table(
        "retrieval_traces",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("normalized_question", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("semantic_candidates", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("keyword_candidates", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("decision_candidates", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("fused_results", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("selected_passage_ids", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("timings", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("configuration", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_retrieval_traces_request_id", "retrieval_traces", ["request_id"])
    op.create_index("ix_retrieval_traces_created_at", "retrieval_traces", ["created_at"])

    op.create_table(
        "evaluation_questions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("dataset_version", sa.String(100), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer_summary", sa.Text(), nullable=True),
        sa.Column("expected_documents", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("expected_passages", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("expected_status", sa.String(30), nullable=True),
        sa.Column("expectation", sa.String(20), nullable=False),
        sa.Column("tags", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        *timestamps(),
        sa.UniqueConstraint("dataset_version", "external_id", name="uq_evaluation_questions_dataset_external_id"),
        sa.CheckConstraint("expectation IN ('answer', 'abstain', 'partial')", name="ck_evaluation_questions_expectation"),
    )
    op.create_index("ix_evaluation_questions_dataset_version", "evaluation_questions", ["dataset_version"])

    op.create_table(
        "evaluation_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("strategy", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("completed_questions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_questions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure", postgresql.JSONB(), nullable=True),
        sa.Column("configuration", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("dataset_version", sa.String(100), nullable=False),
        sa.Column("generation_profile", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("embedding_profile", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("judge_profile", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("aggregate_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("strategy IN ('semantic', 'hybrid')", name="ck_evaluation_runs_strategy"),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_evaluation_runs_status"),
        sa.CheckConstraint("completed_questions >= 0 AND total_questions >= 0 AND completed_questions <= total_questions", name="ck_evaluation_runs_progress"),
    )
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])

    op.create_table(
        "evaluation_results",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_run_id", UUID, nullable=False),
        sa.Column("evaluation_question_id", UUID, nullable=False),
        sa.Column("retrieval_trace_id", UUID, nullable=True),
        sa.Column("retrieved_ranks", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("generated_output", postgresql.JSONB(), nullable=True),
        sa.Column("citation_checks", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("expected_values", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("actual_values", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("judge_prompt", sa.Text(), nullable=True),
        sa.Column("judge_profile", postgresql.JSONB(), nullable=True),
        sa.Column("judge_output", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["evaluation_run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluation_question_id"], ["evaluation_questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retrieval_trace_id"], ["retrieval_traces.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("evaluation_run_id", "evaluation_question_id", name="uq_evaluation_results_run_question"),
    )
    op.create_index("ix_evaluation_results_evaluation_run_id", "evaluation_results", ["evaluation_run_id"])
    op.create_index("ix_evaluation_results_evaluation_question_id", "evaluation_results", ["evaluation_question_id"])


def downgrade() -> None:
    op.drop_table("evaluation_results")
    op.drop_table("evaluation_runs")
    op.drop_table("evaluation_questions")
    op.drop_table("retrieval_traces")
    op.drop_table("ingestion_jobs")
    op.drop_table("decision_revisions")
    op.drop_table("decision_relations")
    op.drop_table("decision_evidence")
    op.drop_table("decisions")
    op.drop_table("passages")
    op.drop_constraint("fk_documents_active_version_id", "documents", type_="foreignkey")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("workspaces")
