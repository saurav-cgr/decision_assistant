"""Make decisions/decision_evidence refs to corpus-derived rows nullable (DB34, US3/D7).

A corpus rebuild (T028) deletes corpus-derived rows (document_versions, passages) while
decisions and decision_evidence must survive. With the original NOT NULL + ON DELETE
CASCADE columns, deleting those rows cascaded the decisions away too. Human-approved
option (a): make both references nullable and switch to ON DELETE SET NULL, so a rebuild
severs the link instead of destroying the decision/evidence row.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_decision_setnull_fk"
down_revision: str | Sequence[str] | None = "0013_eval_run_attempt_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "decisions_document_version_id_fkey", "decisions", type_="foreignkey"
    )
    op.alter_column("decisions", "document_version_id", nullable=True)
    op.create_foreign_key(
        "decisions_document_version_id_fkey",
        "decisions",
        "document_versions",
        ["document_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "decision_evidence_passage_id_fkey", "decision_evidence", type_="foreignkey"
    )
    op.alter_column("decision_evidence", "passage_id", nullable=True)
    op.create_foreign_key(
        "decision_evidence_passage_id_fkey",
        "decision_evidence",
        "passages",
        ["passage_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "decision_evidence_passage_id_fkey", "decision_evidence", type_="foreignkey"
    )
    op.alter_column("decision_evidence", "passage_id", nullable=False)
    op.create_foreign_key(
        "decision_evidence_passage_id_fkey",
        "decision_evidence",
        "passages",
        ["passage_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "decisions_document_version_id_fkey", "decisions", type_="foreignkey"
    )
    op.alter_column("decisions", "document_version_id", nullable=False)
    op.create_foreign_key(
        "decisions_document_version_id_fkey",
        "decisions",
        "document_versions",
        ["document_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
