"""Background dispatch and crash recovery for a corpus rebuild (DB41).

`coordinator.py` runs a rebuild inside one database transaction that commits
only when the whole corpus is re-ingested. That is deliberate (V108: readers
keep seeing the old corpus until the rebuild commits), but it means the
`CorpusRebuild` row cannot live in that transaction: nothing else would see
the row or its progress until the rebuild finished — `GET
/workspaces/{id}/corpus-rebuild` would report the previous run, and T032's
progress UI would have nothing to show.

So the row's lifecycle is committed separately:

- `dispatch_corpus_rebuild` creates the `pending` row and commits it *before*
  starting the long transaction, so it is visible immediately.
- `dispatch_pending_rebuild` continues a row a request already committed
  (T030's retry) and reports progress through the same committing hook.
- Both pass `_progress_hook(...)` into `execute_rebuild`, which writes each
  status/progress change in its own short session and commits it. The long
  transaction never touches `corpus_rebuilds`, so the two never contend for
  the same row lock.
- `mark_interrupted_rebuilds` sweeps rows a crash left `pending`/`running`.
  That sweep is mandatory, not defensive: the partial unique index
  (`uq_corpus_rebuilds_one_active_per_workspace`) blocks every later rebuild
  for that workspace while such a row exists, including T030's retry, which
  only accepts an already-`failed` row.
- All three failure paths (abort, systemic failure, interrupted sweep) write
  `_failed_fields`, so a `failed` row never reports the `documents_completed`
  its rolled-back transaction discarded (DB43/DB44). Add a fourth path by
  calling that helper, not by hand-building the dict.
"""

from datetime import datetime, timezone
from logging import Logger
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.workspace.rebuild.coordinator import (
    ProgressHook,
    RebuildAborted,
    execute_rebuild,
)
from decision_assistant.workspace.rebuild_models import CorpusRebuild

_INTERRUPTED_ERROR_CODE = "rebuild_interrupted"


async def _commit_progress(
    session_factory: async_sessionmaker[AsyncSession],
    rebuild_id: UUID,
    fields: dict[str, Any],
) -> None:
    async with session_factory() as session:
        rebuild = await session.get(CorpusRebuild, rebuild_id)
        if rebuild is None:
            return
        for key, value in fields.items():
            setattr(rebuild, key, value)
        await session.commit()


def _progress_hook(
    session_factory: async_sessionmaker[AsyncSession],
    rebuild_id: UUID,
) -> ProgressHook:
    async def hook(fields: dict[str, Any]) -> None:
        await _commit_progress(session_factory, rebuild_id, fields)

    return hook


def _failed_fields(
    *, error: dict[str, Any], finished_at: datetime
) -> dict[str, Any]:
    """The fields of a `failed` rebuild row, defined in exactly one place.

    DB44: a failed rebuild's data transaction rolled back whole (DB43), so any
    `documents_completed` the progress hook committed while it ran describes
    work that no longer exists. Every failure path therefore resets it to 0 —
    a reader seeing `failed 4/7` would otherwise conclude four documents were
    saved when none were. Iteration 67 reset it only on the `RebuildAborted`
    path; the generic-failure and startup-sweep paths kept the stale count,
    which is what the checker found (V122). This helper exists so the
    invariant cannot drift between the three of them again.
    """
    return {
        "status": "failed",
        "documents_completed": 0,
        "error": error,
        "finished_at": finished_at,
    }


async def mark_interrupted_rebuilds(
    session: AsyncSession,
    *,
    error_code: str = _INTERRUPTED_ERROR_CODE,
) -> list[UUID]:
    """Mark `pending`/`running` rebuilds left behind by a stopped process failed.

    A rebuild's row is committed before its work starts (see the module
    docstring), so a crash leaves it in flight forever and the single-active
    unique index refuses every later rebuild for that workspace. Marking it
    `failed` frees the index and makes T030's retry available. A workspace
    whose corpus still needs rebuilding is re-dispatched by the same startup
    scan that calls this (/workspaces flagged `corpus_reset_required`), so an
    interrupted rebuild recovers without operator action.

    The row goes through `_failed_fields`, so an interrupted rebuild does not
    keep the progress its unfinished transaction never committed (DB44).

    Caller commits.
    """
    rows = list(
        await session.scalars(
            select(CorpusRebuild).where(
                CorpusRebuild.status.in_(("pending", "running"))
            )
        )
    )
    fields = _failed_fields(
        error={"code": error_code}, finished_at=datetime.now(timezone.utc)
    )
    for rebuild in rows:
        for key, value in fields.items():
            setattr(rebuild, key, value)
    await session.flush()
    return [rebuild.id for rebuild in rows]


async def _run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    rebuild_id: UUID,
    workspace_id: UUID,
    settings: object,
    providers: ProviderBundle,
    request_id: str,
    logger: Logger | None,
) -> None:
    async with session_factory() as session:
        try:
            await execute_rebuild(
                session,
                workspace_id=workspace_id,
                progress=_progress_hook(session_factory, rebuild_id),
                settings=settings,
                providers=providers,
                request_id=request_id,
            )
        except RebuildAborted as aborted:
            # DB43: this rollback is the point. The truncation, the re-created
            # documents and every re-link go with it, so the workspace keeps
            # its old corpus and the decisions keep their links; only the
            # rebuild's own row (committed separately, DB41) is marked failed,
            # which is what makes T030's retry re-runnable from real data.
            await session.rollback()
            if logger is not None:
                logger.warning(
                    "corpus rebuild aborted for rebuild %s: %s",
                    rebuild_id,
                    aborted.error,
                )
            try:
                await _commit_progress(
                    session_factory,
                    rebuild_id,
                    _failed_fields(
                        error=aborted.error,
                        finished_at=datetime.now(timezone.utc),
                    ),
                )
            except Exception:  # noqa: BLE001 - the original failure is the interesting one
                if logger is not None:
                    logger.exception(
                        "could not record failure for rebuild %s", rebuild_id
                    )
            return
        except Exception:
            # A systemic failure (snapshot/truncate/dispatch) leaves nothing
            # readable on the row unless it is recorded here; the corpus
            # transaction rolls back whole, so the old corpus is still intact.
            await session.rollback()
            if logger is not None:
                logger.exception("corpus rebuild failed for rebuild %s", rebuild_id)
            try:
                await _commit_progress(
                    session_factory,
                    rebuild_id,
                    _failed_fields(
                        error={"code": "rebuild_failed"},
                        finished_at=datetime.now(timezone.utc),
                    ),
                )
            except Exception:  # noqa: BLE001 - the original failure is the interesting one
                if logger is not None:
                    logger.exception(
                        "could not record failure for rebuild %s", rebuild_id
                    )
            return
        await session.commit()


async def dispatch_corpus_rebuild(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: UUID,
    reason: str,
    settings: object,
    providers: ProviderBundle,
    request_id: str,
    logger: Logger | None = None,
) -> None:
    """Create a `CorpusRebuild` row, commit it, then run it (T029's entry point).

    A background `asyncio.create_task` has no caller to propagate a failure
    to, so a failure to even create the row (the single-active-rebuild unique
    index firing because another rebuild is already in flight) is logged and
    swallowed rather than raised. A per-document ingestion failure aborts the
    rebuild (DB43): `_run` rolls the corpus transaction back and marks this
    row `failed` with the offending document's error code.
    """
    rebuild = CorpusRebuild(
        workspace_id=workspace_id,
        status="pending",
        reason=reason,
        documents_total=0,
        documents_completed=0,
    )
    async with session_factory() as session:
        session.add(rebuild)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            if logger is not None:
                logger.exception(
                    "corpus rebuild could not start for workspace %s", workspace_id
                )
            return
    await _run(
        session_factory,
        rebuild_id=rebuild.id,
        workspace_id=workspace_id,
        settings=settings,
        providers=providers,
        request_id=request_id,
        logger=logger,
    )


async def dispatch_pending_rebuild(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    rebuild_id: UUID,
    settings: object,
    providers: ProviderBundle,
    request_id: str,
    logger: Logger | None = None,
) -> None:
    """Continue an already-created, already-committed `CorpusRebuild` row.

    T030's retry endpoint creates the `pending` row itself (synchronously, in
    the request's own transaction, so `GET .../corpus-rebuild` reflects it
    immediately) and only hands off the long-running work. Unlike
    `dispatch_corpus_rebuild`, this never creates a row itself: doing so would
    race the single-active-rebuild unique index against the row the caller
    already committed. The workspace id is read in its own short session so
    the long transaction never holds the row that the progress hook commits.
    """
    async with session_factory() as session:
        workspace_id = await session.scalar(
            select(CorpusRebuild.workspace_id).where(CorpusRebuild.id == rebuild_id)
        )
    if workspace_id is None:
        return
    await _run(
        session_factory,
        rebuild_id=rebuild_id,
        workspace_id=workspace_id,
        settings=settings,
        providers=providers,
        request_id=request_id,
        logger=logger,
    )
