"""Allow cache-backed passages to omit deprecated duplicate embeddings."""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_nullable_passage_embeddings"
down_revision: str | Sequence[str] | None = "0009_embedding_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("passages", "embedding", nullable=True)
    op.alter_column("passages", "embedding_profile", nullable=True)


def downgrade() -> None:
    op.alter_column("passages", "embedding_profile", nullable=False)
    op.alter_column("passages", "embedding", nullable=False)
