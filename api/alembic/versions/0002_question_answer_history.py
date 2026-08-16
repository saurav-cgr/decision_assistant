"""Add workspace-scoped question answer history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_question_answer_history"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "knowledge_revision",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_workspaces_knowledge_revision_positive",
        "workspaces",
        "knowledge_revision >= 1",
    )

    op.create_table(
        "question_answers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("trace_id", UUID, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column(
            "response_schema_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("knowledge_revision", sa.Integer(), nullable=False),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column(
            "last_asked_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["retrieval_traces.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "normalized_question",
            name="uq_question_answers_workspace_normalized_question",
        ),
        sa.CheckConstraint(
            "response_schema_version >= 1",
            name="ck_question_answers_response_schema_version_positive",
        ),
        sa.CheckConstraint(
            "knowledge_revision >= 1",
            name="ck_question_answers_knowledge_revision_positive",
        ),
    )
    op.create_index(
        "ix_question_answers_workspace_last_asked",
        "question_answers",
        ["workspace_id", "last_asked_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_question_answers_workspace_last_asked",
        table_name="question_answers",
    )
    op.drop_table("question_answers")
    op.drop_constraint(
        "ck_workspaces_knowledge_revision_positive",
        "workspaces",
        type_="check",
    )
    op.drop_column("workspaces", "knowledge_revision")
