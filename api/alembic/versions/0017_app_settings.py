"""Store the selected provider configuration (T050, US6/FR-016).

Until now the two provider names came only from `.env` at startup, so "switch provider" had nowhere
to persist and the contract's `POST /workspace/{id}/provider` could not be honoured. This single-row
table holds the two names; models, dimensions, chunking preset and the rest stay
environment-configured. The row is applied over the environment defaults at startup, so the effective
configuration has one source of truth while a switch survives a restart.

One row, enforced by a check constraint: this is a single-tenant local install, and pretending the
route is per-workspace (it is, for authorization and rebuild dispatch) while the provider choice is
global is a deliberate, recorded deviation — see the T050 task note and debt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_app_settings"
down_revision: str | Sequence[str] | None = "0016_evidence_quote"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "app_settings"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generation_provider", sa.String(length=32), nullable=False),
        sa.Column("embedding_provider", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_app_settings_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
