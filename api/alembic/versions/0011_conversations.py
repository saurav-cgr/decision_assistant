"""Add workspace-scoped resumable conversations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_conversations"
down_revision: str | Sequence[str] | None = "0010_nullable_passage_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_conversations_workspace_updated",
        "conversations",
        ["workspace_id", "updated_at", "id"],
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("trace_id", UUID, nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column(
            "response_schema_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("knowledge_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"], ["retrieval_traces.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "turn_number",
            name="uq_conversation_messages_turn",
        ),
        sa.CheckConstraint(
            "turn_number >= 1",
            name="ck_conversation_messages_turn_number_positive",
        ),
        sa.CheckConstraint(
            "response_schema_version >= 1",
            name="ck_conversation_messages_response_schema_version_positive",
        ),
        sa.CheckConstraint(
            "knowledge_revision >= 1",
            name="ck_conversation_messages_knowledge_revision_positive",
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_messages")
    op.drop_index(
        "ix_conversations_workspace_updated",
        table_name="conversations",
    )
    op.drop_table("conversations")
