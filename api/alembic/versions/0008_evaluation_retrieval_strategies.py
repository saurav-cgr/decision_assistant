"""Allow persisted retrieval-unit evaluation strategies."""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_eval_retrieval_strategies"
down_revision: str | Sequence[str] | None = "0007_retrieval_unit_hierarchy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRATEGY_CHECK = (
    "strategy IN ('semantic', 'hybrid', 'passage_hybrid', "
    "'sentence_expanded', 'parent_child_merged')"
)


def upgrade() -> None:
    op.drop_constraint("ck_evaluation_runs_strategy", "evaluation_runs", type_="check")
    op.create_check_constraint(
        "ck_evaluation_runs_strategy",
        "evaluation_runs",
        _STRATEGY_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint("ck_evaluation_runs_strategy", "evaluation_runs", type_="check")
    op.create_check_constraint(
        "ck_evaluation_runs_strategy",
        "evaluation_runs",
        "strategy IN ('semantic', 'hybrid')",
    )
