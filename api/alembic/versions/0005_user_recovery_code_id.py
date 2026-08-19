"""Add an indexed public identifier to recovery credentials."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_user_recovery_code_id"
down_revision: str | Sequence[str] | None = "0004_authentication_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("recovery_code_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    connection = op.get_bind()
    users = connection.execute(sa.text("SELECT id FROM users")).all()
    for (user_id,) in users:
        connection.execute(
            sa.text(
                "UPDATE users SET recovery_code_id = :recovery_code_id "
                "WHERE id = :id"
            ),
            {"id": user_id, "recovery_code_id": uuid4()},
        )
    op.alter_column("users", "recovery_code_id", nullable=False)
    op.create_unique_constraint(
        "uq_users_recovery_code_id",
        "users",
        ["recovery_code_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_recovery_code_id", "users", type_="unique")
    op.drop_column("users", "recovery_code_id")
