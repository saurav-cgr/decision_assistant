"""Persist structured answer diagnostics for evaluation results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_eval_answer_diagnostics"
down_revision: str | None = "0002_question_answer_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_results",
        sa.Column(
            "answer_diagnostics",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("evaluation_results", "answer_diagnostics")
