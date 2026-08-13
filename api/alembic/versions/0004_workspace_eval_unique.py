"""Scope evaluation-question uniqueness per workspace."""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_workspace_eval_unique"
down_revision: str | None = "0003_workspace_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_evaluation_questions_dataset_external_id",
        "evaluation_questions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_evaluation_questions_workspace_dataset_external_id",
        "evaluation_questions",
        ["workspace_id", "dataset_version", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_evaluation_questions_workspace_dataset_external_id",
        "evaluation_questions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_evaluation_questions_dataset_external_id",
        "evaluation_questions",
        ["dataset_version", "external_id"],
    )
