"""Add decisions.workspace_id so a decision survives a nulled document_version_id (DB38).

Decisions were only workspace-scoped through `document_version_id` -> `documents`
-> `workspace_id`. Revision 0014 (DB34) makes `document_version_id` nullable
for a corpus rebuild, which meant a rebuilt decision dropped out of
`GET /decisions` (workspace-scoped listing) and 404'd on `GET /decisions/{id}`
(DB38) — the exact "readable and unchanged" survival D7 requires. Denormalizing
`workspace_id` onto `decisions` directly, independent of the corpus-derived
chain, is the only way workspace membership survives a rebuild.

DB39 (checker V106, human decision 2026-09-26): a DB at 0014 whose decisions
were already orphaned (document or workspace deleted, `document_version_id`
set NULL by 0014's `ON DELETE SET NULL`) has no workspace left to backfill
from, so the `SET NOT NULL` below failed with `NotNullViolationError`. These
rows are pre-existing orphans with no readable evidence chain regardless of
this revision, so the upgrade deletes them before enforcing NOT NULL. This is
data deletion, scoped only to decisions the backfill could not attach to any
workspace; dev-only exposure since 0014/0015 are unreleased and untracked.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_decisions_workspace_id"
down_revision: str | Sequence[str] | None = "0014_decision_setnull_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decisions",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE decisions
        SET workspace_id = documents.workspace_id
        FROM document_versions
        JOIN documents ON documents.id = document_versions.document_id
        WHERE document_versions.id = decisions.document_version_id
        """
    )
    op.execute("DELETE FROM decisions WHERE workspace_id IS NULL")
    op.alter_column("decisions", "workspace_id", nullable=False)
    op.create_foreign_key(
        "decisions_workspace_id_fkey",
        "decisions",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_decisions_workspace_id", "decisions", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_decisions_workspace_id", table_name="decisions")
    op.drop_constraint("decisions_workspace_id_fkey", "decisions", type_="foreignkey")
    op.drop_column("decisions", "workspace_id")
