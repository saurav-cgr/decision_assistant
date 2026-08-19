"""Add local user records and owner-scoped workspaces."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_authentication_ownership"
down_revision: str | None = "0003_eval_answer_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("recovery_code_hash", sa.Text(), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.add_column(
        "workspaces",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_workspaces_owner_user_id",
        "workspaces",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])
    op.drop_index("uq_workspaces_one_active", table_name="workspaces")
    op.drop_constraint("uq_workspaces_name", "workspaces", type_="unique")
    op.create_unique_constraint(
        "uq_workspaces_owner_name",
        "workspaces",
        ["owner_user_id", "name"],
    )
    op.create_index(
        "uq_workspaces_one_active_per_owner",
        "workspaces",
        ["owner_user_id", "is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND owner_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspaces_one_active_per_owner", table_name="workspaces")
    op.drop_constraint("uq_workspaces_owner_name", "workspaces", type_="unique")
    op.create_unique_constraint("uq_workspaces_name", "workspaces", ["name"])
    op.create_index(
        "uq_workspaces_one_active",
        "workspaces",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_constraint("fk_workspaces_owner_user_id", "workspaces", type_="foreignkey")
    op.drop_column("workspaces", "owner_user_id")
    op.drop_table("users")
