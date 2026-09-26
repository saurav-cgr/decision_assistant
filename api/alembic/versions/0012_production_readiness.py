"""Add corpus_rebuilds tracking, stale-citation flag, and disclosure acknowledgement."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_production_readiness"
down_revision: str | Sequence[str] | None = "0011_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "corpus_rebuilds",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("documents_total", sa.Integer(), nullable=False),
        sa.Column("documents_completed", sa.Integer(), nullable=False),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_corpus_rebuilds_status",
        ),
    )
    op.create_index(
        "ix_corpus_rebuilds_workspace_id",
        "corpus_rebuilds",
        ["workspace_id"],
    )
    op.create_index(
        "uq_corpus_rebuilds_one_active_per_workspace",
        "corpus_rebuilds",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )

    op.add_column(
        "decision_evidence",
        sa.Column(
            "citation_stale",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.add_column(
        "workspaces",
        sa.Column("disclosure_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "disclosure_acknowledged_at")
    op.drop_column("decision_evidence", "citation_stale")
    op.drop_index(
        "uq_corpus_rebuilds_one_active_per_workspace",
        table_name="corpus_rebuilds",
    )
    op.drop_index("ix_corpus_rebuilds_workspace_id", table_name="corpus_rebuilds")
    op.drop_table("corpus_rebuilds")
