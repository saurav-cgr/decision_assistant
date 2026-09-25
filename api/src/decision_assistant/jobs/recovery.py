from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RecoveryOutcome:
    """Rows swept by `recover_and_requeue`, split by what happened to each."""

    requeued: list[Any] = field(default_factory=list)
    failed: list[Any] = field(default_factory=list)


async def recover_and_requeue(
    session: AsyncSession,
    *,
    model: type,
    max_attempts: int,
    interrupted_error_code: str,
) -> RecoveryOutcome:
    """Sweep rows left `running` by a stopped process.

    A row under `max_attempts` is requeued (`status` -> `pending`,
    `attempt_count` incremented); a row at or over `max_attempts` is marked
    terminal `failed` with `error = {"code": interrupted_error_code}`.

    Only mutates `status`/`attempt_count`/`error` on `model` — both
    `IngestionJob` and `EvaluationRun` share this shape, but any
    model-specific side effect (re-dispatching work, updating a linked
    record) is the caller's responsibility, since those effects differ
    between ingestion and evaluation recovery.
    """
    rows = list(
        await session.scalars(select(model).where(model.status == "running"))
    )
    outcome = RecoveryOutcome()
    for row in rows:
        if row.attempt_count < max_attempts:
            row.attempt_count += 1
            row.status = "pending"
            outcome.requeued.append(row)
        else:
            row.status = "failed"
            row.error = {"code": interrupted_error_code}
            outcome.failed.append(row)
    await session.flush()
    return outcome
