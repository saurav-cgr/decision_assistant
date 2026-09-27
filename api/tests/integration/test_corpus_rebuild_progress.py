"""DB41: a rebuild's row and progress are visible while the rebuild runs.

`execute_rebuild` deliberately keeps the whole corpus swap in one transaction
(readers keep seeing the old corpus until it commits, V108), so the
`CorpusRebuild` row cannot live in that transaction: nothing would see the row
or its progress until the rebuild finished, and `GET
/workspaces/{id}/corpus-rebuild` would report the previous run for its whole
duration.

`dispatch_corpus_rebuild` therefore commits the row before starting the work
and reports progress through a hook that commits each update in its own
session. The second half of that design is the recovery sweep: a row committed
before its work starts stays `pending`/`running` forever after a crash, and
the single-active-rebuild unique index then refuses every later rebuild for
that workspace.

These tests need more than one independent transaction (a watcher must see the
row while the rebuild's transaction is still open), so they open their own
engine/sessions rather than the shared `db_session` fixture, and delete what
they commit (M-037).
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from decision_assistant.config import Settings
from decision_assistant.db import create_engine
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.models import Document
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import FakeEmbeddingProvider, FakeGenerationProvider
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.rebuild.dispatch import (
    dispatch_corpus_rebuild,
    mark_interrupted_rebuilds,
)
from decision_assistant.workspace.rebuild_models import CorpusRebuild

_METADATA_RESPONSE = {
    "title": "Architecture Sync",
    "document_date": "2026-07-15",
    "participants": ["Maya", "Ravi"],
    "source_type": "meeting",
    "project": "Atlas",
}

_SOURCE_TEXT = """---
title: Architecture Sync
date: 2026-07-15
participants: [Maya, Ravi]
source_type: meeting
project: Atlas
---

# Authentication

Authentication was postponed until the import flow is stable.
"""


class _GatedEmbeddingProvider(FakeEmbeddingProvider):
    """Signals when the rebuild has reached embedding, then waits for release."""

    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(dimension=768)
        self._started = started
        self._release = release
        self._gated = False

    async def embed(self, texts, *, purpose):  # noqa: ANN001, ANN201 - provider protocol
        if not self._gated:
            self._gated = True
            self._started.set()
            await self._release.wait()
        return await super().embed(texts, purpose=purpose)


def _providers(*, embedding) -> ProviderBundle:  # noqa: ANN001 - test helper
    return ProviderBundle(
        embedding=embedding,
        generation=FakeGenerationProvider([_METADATA_RESPONSE]),
    )


async def _seed_active_document(factory, tmp_path: Path):  # noqa: ANN001, ANN201
    workspace_id = uuid4()
    document_id = uuid4()
    upload_directory = tmp_path / "uploads"
    source_path = tmp_path / "source" / "meeting.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(_SOURCE_TEXT, encoding="utf-8")

    async with factory() as session:
        session.add(Workspace(id=workspace_id, name=f"Progress {workspace_id}"))
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
        service = IngestionService(
            session=session,
            embedding_provider=FakeEmbeddingProvider(dimension=768),
            decision_extractor=DecisionExtractor(FakeGenerationProvider()),
            metadata_extractor=MetadataExtractor(
                FakeGenerationProvider([_METADATA_RESPONSE])
            ),
            upload_directory=upload_directory,
        )
        await service.ingest(
            document_id,
            source_path,
            request_id=str(uuid4()),
            job_id=None,
            extract_decisions=False,
        )
        await session.commit()
    return workspace_id, document_id, upload_directory


@pytest.mark.asyncio
async def test_rebuild_progress_is_visible_while_the_rebuild_runs(
    tmp_path: Path,
) -> None:
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, document_id, upload_directory = await _seed_active_document(
        factory, tmp_path
    )
    started = asyncio.Event()
    release = asyncio.Event()
    task = asyncio.create_task(
        dispatch_corpus_rebuild(
            factory,
            workspace_id=workspace_id,
            reason="corpus_reset_required",
            settings=Settings(upload_directory=upload_directory),
            providers=_providers(
                embedding=_GatedEmbeddingProvider(started, release)
            ),
            request_id=str(uuid4()),
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=20)
        # The rebuild's own transaction is still open here (it is blocked in
        # embedding), yet the row and its progress are already visible.
        async with factory() as observer:
            rebuild = await observer.scalar(
                select(CorpusRebuild).where(
                    CorpusRebuild.workspace_id == workspace_id
                )
            )
            assert rebuild is not None, (
                "the rebuild row must be committed before the work starts (DB41)"
            )
            assert rebuild.status == "running"
            assert rebuild.documents_total == 1
            assert rebuild.documents_completed == 0
            assert rebuild.started_at is not None
            assert rebuild.finished_at is None

        release.set()
        await asyncio.wait_for(task, timeout=120)

        async with factory() as observer:
            rebuild = await observer.scalar(
                select(CorpusRebuild).where(
                    CorpusRebuild.workspace_id == workspace_id
                )
            )
        assert rebuild.status == "completed"
        assert rebuild.documents_total == 1
        assert rebuild.documents_completed == 1
        assert rebuild.finished_at is not None
    finally:
        release.set()
        if not task.done():
            task.cancel()
        async with factory() as cleanup:
            await cleanup.execute(
                delete(Workspace).where(Workspace.id == workspace_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupted_rebuild_row_is_recovered_and_unblocks_dispatch() -> None:
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id = uuid4()
    rebuild_id = uuid4()
    try:
        async with factory() as session:
            session.add(Workspace(id=workspace_id, name=f"Recover {workspace_id}"))
            session.add(
                CorpusRebuild(
                    id=rebuild_id,
                    workspace_id=workspace_id,
                    status="running",
                    reason="corpus_reset_required",
                    documents_total=2,
                    # Non-zero on purpose (DB44): the sweep must not leave a
                    # failed row claiming progress whose transaction never
                    # committed.
                    documents_completed=1,
                    started_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

        # While the stale row is in flight the single-active index refuses a new
        # one — this is the block DB41's recovery exists to clear.
        async with factory() as session:
            session.add(
                CorpusRebuild(
                    workspace_id=workspace_id,
                    status="pending",
                    reason="manual_retry",
                    documents_total=0,
                    documents_completed=0,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        async with factory() as session:
            recovered = await mark_interrupted_rebuilds(session)
            await session.commit()
        assert rebuild_id in recovered

        async with factory() as session:
            stale = await session.get(CorpusRebuild, rebuild_id)
            assert stale.status == "failed"
            assert stale.error == {"code": "rebuild_interrupted"}
            assert stale.finished_at is not None
            assert stale.documents_completed == 0, (
                "the sweep must clear progress the interrupted transaction "
                f"never committed: {stale.documents_completed}/{stale.documents_total}"
            )
            # The index is free, so the next startup scan (or a retry) can
            # insert a fresh rebuild for this workspace.
            session.add(
                CorpusRebuild(
                    workspace_id=workspace_id,
                    status="pending",
                    reason="manual_retry",
                    documents_total=0,
                    documents_completed=0,
                )
            )
            await session.commit()
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                delete(Workspace).where(Workspace.id == workspace_id)
            )
            await cleanup.commit()
        await engine.dispose()
