"""Store the evidence quote on `decision_evidence` so a rebuild can re-link it (DB40).

Before this revision a quote was never stored, only derived: every reader
sliced `passages.content[start_offset:end_offset]` for the passage the
evidence pointed at. A corpus rebuild deletes and recreates those passages, so
after a rebuild the slice either pointed at reshaped text or had no passage at
all (`passage_id` NULL, `citation_stale = true`) and the quote was lost even
though the decision survived.

Storing the exact extracted quote on the evidence row makes the quote survive
independently of any passage and lets a rebuild re-link evidence to a new
passage by locating the quote's text inside it (see
`workspace/rebuild/coordinator.py`), instead of only matching whole-chunk
`content_hash` values. The backfill reproduces the derived value for every
existing row that still has a passage; rows whose `passage_id` was already
nulled by an earlier rebuild keep a NULL quote (nothing is recoverable for
them). The column stays nullable for that reason — a novel rebuild can still
lose a quote if its source text genuinely changed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_evidence_quote"
down_revision: str | Sequence[str] | None = "0015_decisions_workspace_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_evidence",
        sa.Column("quote", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE decision_evidence
        SET quote = substring(
            passages.content
            FROM decision_evidence.start_offset + 1
            FOR decision_evidence.end_offset - decision_evidence.start_offset
        )
        FROM passages
        WHERE passages.id = decision_evidence.passage_id
        """
    )


def downgrade() -> None:
    op.drop_column("decision_evidence", "quote")
