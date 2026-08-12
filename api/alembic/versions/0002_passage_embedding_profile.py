"""Track the embedding profile used for each passage vector."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_passage_embedding_profile"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "passages",
        sa.Column("embedding_profile", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("passages", "embedding_profile")
