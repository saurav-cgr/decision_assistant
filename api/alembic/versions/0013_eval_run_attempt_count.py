"""Add attempt_count to evaluation_runs for startup recovery (T023)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_eval_run_attempt_count"
down_revision: str | Sequence[str] | None = "0012_production_readiness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("evaluation_runs", "attempt_count")
