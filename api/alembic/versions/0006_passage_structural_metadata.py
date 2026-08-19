"""Add passages.structural_metadata for persisted structural context."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_passage_structural_metadata"
down_revision: str | Sequence[str] | None = "0005_user_recovery_code_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "passages",
        sa.Column(
            "structural_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("passages", "structural_metadata")
