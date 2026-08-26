"""Add workspace-scoped exact-content embedding cache."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0009_embedding_cache"
down_revision: str | Sequence[str] | None = "0008_eval_retrieval_strategies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "embedding_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "embedding_profile_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("embedding_profile", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "content_hash",
            "embedding_profile_fingerprint",
            name="uq_embedding_cache_content_profile",
        ),
    )
    op.create_index(
        "ix_embedding_cache_workspace_id",
        "embedding_cache",
        ["workspace_id"],
    )
    op.create_index(
        "ix_embedding_cache_embedding_hnsw",
        "embedding_cache",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.add_column(
        "passages",
        sa.Column("embedding_cache_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_passages_embedding_cache_id",
        "passages",
        "embedding_cache",
        ["embedding_cache_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_passages_embedding_cache_id",
        "passages",
        ["embedding_cache_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_passages_embedding_cache_id", table_name="passages")
    op.drop_constraint(
        "fk_passages_embedding_cache_id", "passages", type_="foreignkey"
    )
    op.drop_column("passages", "embedding_cache_id")
    op.drop_index(
        "ix_embedding_cache_embedding_hnsw", table_name="embedding_cache"
    )
    op.drop_index("ix_embedding_cache_workspace_id", table_name="embedding_cache")
    op.drop_table("embedding_cache")
