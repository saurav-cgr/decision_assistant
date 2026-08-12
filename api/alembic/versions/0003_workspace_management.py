"""Multi-workspace management: status, active flag, and isolation FKs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_workspace_management"
down_revision: str | None = "0002_passage_embedding_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Legacy data carried no workspace linkage and predates multiple workspaces, so
# every pre-existing trace/question/run attaches to the first (only) workspace.
_FIRST_WORKSPACE = "SELECT id FROM workspaces ORDER BY created_at ASC LIMIT 1"

_ISOLATED_TABLES = (
    "retrieval_traces",
    "evaluation_questions",
    "evaluation_runs",
)


def upgrade() -> None:
    # citext powers case-insensitive unique workspace names.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # --- Workspace management columns -----------------------------------
    op.add_column(
        "workspaces",
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    # Case-insensitive unique names.
    op.alter_column(
        "workspaces",
        "name",
        existing_type=sa.String(200),
        type_=postgresql.CITEXT(),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_workspaces_status",
        "workspaces",
        "status IN ('active', 'archived')",
    )
    op.create_index(
        "uq_workspaces_one_active",
        "workspaces",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    # Promote the existing single workspace to the active workspace.
    op.execute("UPDATE workspaces SET is_active = true, status = 'active'")

    # --- Workspace isolation FKs ----------------------------------------
    for table in _ISOLATED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.execute(f"UPDATE {table} SET workspace_id = ({_FIRST_WORKSPACE})")
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_workspace_id",
            table,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])

    # Evaluation questions are unique per workspace + dataset entry.
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

    for table in _ISOLATED_TABLES:
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_column(table, "workspace_id")

    op.drop_index("uq_workspaces_one_active", table_name="workspaces")
    op.drop_constraint("ck_workspaces_status", "workspaces", type_="check")
    op.alter_column(
        "workspaces",
        "name",
        existing_type=postgresql.CITEXT(),
        type_=sa.String(200),
        existing_nullable=False,
    )
    op.drop_column("workspaces", "is_active")
    op.drop_column("workspaces", "status")
