"""T062 (US8/FR-022): one slow document must not wedge ingestion for the next one.

The test runs the **real** `LocalIngestionDispatcher` -> `IngestionService.ingest` path against
deterministic fake providers, with the parse budget cut to a fraction of a second so the real Docling
parse of the fixture PDF cannot finish inside it. Since DB60 the parse runs in a child process, so the
budget is bound by `pdf_parse_timeout_seconds` and the timeout kills the child instead of abandoning a
worker thread: the test asserts both halves — a sanitized, non-retryable failure, **no surviving parse
child** (checker V139's break was a parse that kept running), and a next document that still ingests to
`completed` on the same dispatcher and event loop.
"""

import multiprocessing
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.documents.router import LocalIngestionDispatcher
from decision_assistant.ingestion import service as ingestion_service
from decision_assistant.ingestion.models import Document, DocumentVersion, IngestionJob
from decision_assistant.workspace.models import Workspace
from tests.support.ingestion_fixtures import (
    FakeProviderBundleFactory,
    cleanup_workspace,
    loop_local_dispatch_session_factory,
)

PDF_FIXTURE = Path("tests/fixtures/text.pdf")

#: Far below the time Docling needs to load its models, so the real parse always exceeds it. Nothing
#: is slowed down artificially any more: the parse is genuine, the budget is what is tiny.
_PARSE_BUDGET_SECONDS = 0.2

MARKDOWN_CONTENT = """---
title: Parse Timeout Recovery
date: 2026-07-21
participants: [Priya]
source_type: incident-review
project: Atlas
---

# Parse Timeout Recovery

A document that timed out must not stop the next document from being ingested.
"""


async def _seed_job(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    workspace_name: str,
    filename: str,
    content: bytes,
    media_type: str,
    request_id: str,
) -> tuple[IngestionJob, Document, DocumentVersion, object]:
    workspace = Workspace(name=workspace_name, embedding_profile=None)
    db_session.add(workspace)
    await db_session.flush()

    document = Document(
        workspace_id=workspace.id,
        display_name=filename,
        media_type=media_type,
    )
    db_session.add(document)
    await db_session.flush()

    source_file = tmp_path / filename
    source_file.write_bytes(content)

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        checksum="c" * 64,
        storage_path=source_file.name,
        state="staging",
    )
    db_session.add(version)
    await db_session.flush()

    job = IngestionJob(
        document_id=document.id,
        document_version_id=version.id,
        stage="parsing",
        status="running",
        progress=0,
        attempt_count=0,
        request_id=request_id,
    )
    db_session.add(job)
    await db_session.flush()
    await db_session.commit()  # the dispatch path reads through its own connection
    return job, document, version, workspace.id


@pytest.mark.asyncio
async def test_a_timed_out_parse_fails_its_document_and_the_next_document_still_ingests(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        upload_directory=tmp_path,
        pdf_parse_timeout_seconds=_PARSE_BUDGET_SECONDS,
    )
    # `_parse_for_ingestion` reads the process-wide cached `get_settings()`, not the dispatcher's own
    # Settings object, so the budget that governs it has to be patched where it is read.
    monkeypatch.setattr(ingestion_service, "get_settings", lambda: settings)

    slow_job, slow_document, slow_version, slow_workspace_id = await _seed_job(
        db_session,
        tmp_path,
        workspace_name="parse-timeout-slow",
        filename="slow.pdf",
        content=PDF_FIXTURE.read_bytes(),
        media_type="application/pdf",
        request_id="parse-timeout",
    )

    async with cleanup_workspace(db_session, slow_workspace_id):
        async with loop_local_dispatch_session_factory(monkeypatch):
            dispatcher = LocalIngestionDispatcher(settings, FakeProviderBundleFactory())

            await dispatcher.dispatch(
                document_id=slow_document.id,
                job_id=slow_job.id,
                source_path=tmp_path / "slow.pdf",
                request_id="parse-timeout",
            )

            await db_session.refresh(slow_job)
            await db_session.refresh(slow_version)
            assert slow_job.status == "failed"
            assert slow_job.error is not None
            assert slow_job.error["code"] == "pdf_parse_timeout"
            # FR-022 wants a bounded parse, not a retry loop: the failure is terminal and sanitized.
            assert slow_job.error["retryable"] is False
            assert slow_job.finished_at is not None
            assert slow_version.state == "failed"
            # DB60/V139: the timed-out parse was killed, not merely abandoned. Without this the test
            # passes again while a Docling child (or, in the old design, a thread) keeps a core and
            # gigabytes of RSS alive.
            assert [
                child
                for child in multiprocessing.active_children()
                if child.name == "docling-parse"
            ] == []

            # Same dispatcher, same event loop, immediately afterwards. If the timed-out parse had
            # blocked the loop or poisoned the dispatcher, this document would not ingest.
            normal_job, normal_document, normal_version, normal_workspace_id = await _seed_job(
                db_session,
                tmp_path,
                workspace_name="parse-timeout-recovery",
                filename="recovery.md",
                content=MARKDOWN_CONTENT.encode(),
                media_type="text/markdown",
                request_id="parse-timeout-recovery",
            )

            async with cleanup_workspace(db_session, normal_workspace_id):
                await dispatcher.dispatch(
                    document_id=normal_document.id,
                    job_id=normal_job.id,
                    source_path=tmp_path / "recovery.md",
                    request_id="parse-timeout-recovery",
                )

                await db_session.refresh(normal_job)
                await db_session.refresh(normal_version)
                assert normal_job.status == "completed"
                assert normal_job.error is None
                assert normal_version.state == "active"
