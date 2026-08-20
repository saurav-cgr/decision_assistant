"""Add persisted retrieval-unit kinds and sentence-parent links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_retrieval_unit_hierarchy"
down_revision: str | Sequence[str] | None = "0006_passage_structural_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "passages",
        sa.Column(
            "retrieval_unit_kind",
            sa.String(length=20),
            server_default=sa.text("'passage'"),
            nullable=False,
        ),
    )
    op.add_column(
        "passages",
        sa.Column(
            "parent_passage_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_passages_parent_passage_id",
        "passages",
        "passages",
        ["parent_passage_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_passages_parent_passage_id",
        "passages",
        ["parent_passage_id"],
    )
    op.create_check_constraint(
        "ck_passages_retrieval_unit_kind",
        "passages",
        "retrieval_unit_kind IN ('passage', 'parent', 'sentence')",
    )
    op.create_check_constraint(
        "ck_passages_parent_unit_link",
        "passages",
        "(retrieval_unit_kind = 'sentence' AND parent_passage_id IS NOT NULL) "
        "OR (retrieval_unit_kind <> 'sentence' AND parent_passage_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_passages_parent_unit_link", "passages", type_="check")
    op.drop_constraint("ck_passages_retrieval_unit_kind", "passages", type_="check")
    op.drop_index("ix_passages_parent_passage_id", table_name="passages")
    op.drop_constraint("fk_passages_parent_passage_id", "passages", type_="foreignkey")
    op.drop_column("passages", "parent_passage_id")
    op.drop_column("passages", "retrieval_unit_kind")
