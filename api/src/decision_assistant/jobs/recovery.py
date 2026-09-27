from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

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
    statuses: Sequence[str] = ("running",),
    error_field: str = "error",
    finished_at_field: str | None = None,
) -> RecoveryOutcome:
    """Sweep rows left in a stale in-flight `status` by a stopped process.

    A row under `max_attempts` is requeued (`status` -> `pending`,
    `attempt_count` incremented); a row at or over `max_attempts` is marked
    terminal `failed` with `error_field` set to `{"code": interrupted_error_code}`
    and, when `finished_at_field` is given, that column stamped with the
    current time — matching a normal terminal `failed` transition elsewhere
    (e.g. `documents/router.py`'s `_record_dispatch_failure`,
    `evaluation/service.py`'s `_fail_run`), which both stamp their terminal
    timestamp. `finished_at_field` defaults to `None` (no stamp) rather than
    a shared default name, since `IngestionJob` calls it `finished_at` and
    `EvaluationRun` calls it `completed_at`.

    `statuses` defaults to `("running",)`. A caller whose dispatch can crash
    before a row ever reaches `running` (DB27: a job created `pending` and
    fire-and-forgotten to a background task, killed before it starts) should
    pass `statuses=("running", "pending")` so a restart's sweep can find it
    too — a `pending` row is only stale at startup, since during normal
    operation a freshly created row moves out of `pending` within the same
    request that created it.

    `error_field` defaults to `"error"` (`IngestionJob`'s column). `EvaluationRun`
    (T023) names its equivalent column `failure`, not `error` — setting a
    plain `row.error = ...` on it would silently create an unmapped, unpersisted
    Python attribute rather than raise, so the field name is a required choice,
    not an assumption. Pass `error_field="failure"` for `EvaluationRun`.

    Only mutates `status`/`attempt_count`/`error_field` on `model` — both
    `IngestionJob` and `EvaluationRun` share this shape otherwise, but any
    model-specific side effect (re-dispatching work, updating a linked
    record) is the caller's responsibility, since those effects differ
    between ingestion and evaluation recovery.
    """
    rows = list(
        await session.scalars(select(model).where(model.status.in_(statuses)))
    )
    outcome = RecoveryOutcome()
    for row in rows:
        if row.attempt_count < max_attempts:
            row.attempt_count += 1
            row.status = "pending"
            outcome.requeued.append(row)
        else:
            row.status = "failed"
            setattr(row, error_field, {"code": interrupted_error_code})
            if finished_at_field is not None:
                setattr(row, finished_at_field, datetime.now(timezone.utc))
            outcome.failed.append(row)
    await session.flush()
    return outcome
