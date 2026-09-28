"""DB31: two retries that arrive at the same time must not both dispatch.

`DocumentService.retry` locks the document row (`SELECT ... FOR UPDATE`) before
reading the latest `IngestionJob`, so the second concurrent caller blocks until
the first one's transaction commits, then re-reads the latest job (now
`pending`) and is rejected with 409.

These tests need two real, independent transactions, so they open their own
engine/sessions instead of using the shared `db_session` fixture — that fixture
binds everything in a test to one session, which would make the lock re-entrant
and the race untestable. Rows are committed and deleted again by this file
(M-037: a real-DB test sharing a session-scoped database must clean up itself).
"""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_assistant.config import Settings
from decision_assistant.db import create_engine
from decision_assistant.documents.service import DocumentApiError, DocumentService
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    IngestionJob,
)
from decision_assistant.workspace.models import Workspace

RETRY_LOCK_HEAD_START_SECONDS = 0.2


class _NoopDispatcher:
    """`retry` only builds a `DispatchRequest`; nothing has to consume it."""

    async def dispatch(self, **_kwargs: object) -> None:
        return None


def _service(session: AsyncSession, tmp_path: Path) -> DocumentService:
    return DocumentService(
        session=session,
        settings=Settings(upload_directory=tmp_path / "uploads"),
        dispatcher=_NoopDispatcher(),
    )


async def _seed_failed_document(
    session: AsyncSession, workspace_id: UUID
) -> tuple[UUID, UUID]:
    document_id = uuid4()
    version_id = uuid4()
    # Commit one level at a time: SQLAlchemy does not order a multi-table flush
    # by foreign key here (adding all four rows at once inserts `documents`
    # before `workspaces` and fails `documents_workspace_id_fkey`). The rest of
    # this suite seeds the same way — create the parent, flush, then the child.
    session.add(
        Workspace(
            id=workspace_id,
            name=f"Retry race workspace {workspace_id}",
            embedding_profile=None,
        )
    )
    await session.flush()
    session.add(
        Document(
            id=document_id,
            workspace_id=workspace_id,
            display_name="meeting.md",
            media_type="text/markdown",
        )
    )
    await session.flush()
    session.add(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            checksum="c" * 64,
            storage_path="meeting.md",
            state="staging",
        )
    )
    session.add(
        IngestionJob(
            document_id=document_id,
            document_version_id=version_id,
            stage="queued",
            status="failed",
            progress=100,
            attempt_count=0,
            error={"code": "provider_unavailable"},
            request_id="seed",
        )
    )
    await session.commit()
    return document_id, version_id


async def _job_count(session: AsyncSession, document_id: UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(IngestionJob.document_id == document_id)
        )
    ) or 0


@pytest.mark.asyncio
async def test_concurrent_retry_dispatches_only_once(tmp_path: Path) -> None:
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id = uuid4()
    seed_session = factory()
    try:
        document_id, _ = await _seed_failed_document(seed_session, workspace_id)

        winner = factory()
        loser = factory()
        try:
            # The winner takes the row lock and inserts its `pending` job, but
            # does NOT commit yet — exactly the in-flight window DB31 describes.
            first = await _service(winner, tmp_path).retry(
                document_id, request_id="retry-winner"
            )
            assert first.response.job_id is not None

            second = asyncio.create_task(
                _service(loser, tmp_path).retry(document_id, request_id="retry-loser")
            )
            await asyncio.sleep(RETRY_LOCK_HEAD_START_SECONDS)
            assert not second.done(), (
                "the second retry was not blocked by the document row lock — it "
                "read the same `failed` job the first one started from"
            )

            await winner.commit()

            with pytest.raises(DocumentApiError) as raised:
                await asyncio.wait_for(second, timeout=10)
            assert raised.value.code == "retry_not_available"
            assert raised.value.status_code == 409

            # Original failed job + exactly one dispatched retry.
            assert await _job_count(loser, document_id) == 2
        finally:
            await winner.rollback()
            await loser.rollback()
            await winner.close()
            await loser.close()
    finally:
        # `workspaces.id` cascades through documents/versions/jobs.
        await seed_session.execute(
            delete(Workspace).where(Workspace.id == workspace_id)
        )
        await seed_session.commit()
        await seed_session.close()
        await engine.dispose()
