from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.models import (
    Decision,
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
)
from decision_assistant.providers.base import ProviderUnavailable
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.workspace.service import WorkspaceService

GOOD_CONTENT = """---
title: Architecture Sync
date: 2026-07-15
participants: [Maya, Ravi]
source_type: meeting
project: Atlas
---

# Authentication

Authentication was postponed until the import flow is stable.
"""

CHANGED_CONTENT = GOOD_CONTENT.replace(
    "Authentication was postponed",
    "Authentication will be implemented",
)


async def create_harness(
    db_session: AsyncSession,
    tmp_path: Path,
) -> tuple[IngestionService, Document, FakeEmbeddingProvider]:
    workspace = await WorkspaceService(db_session).get_or_create(
        name=f"Test workspace {uuid4()}"
    )
    document = Document(
        workspace_id=workspace.id,
        display_name="meeting.md",
        media_type="text/markdown",
    )
    db_session.add(document)
    await db_session.flush()

    embedding_provider = FakeEmbeddingProvider(dimension=768)
    decision_provider = FakeGenerationProvider([{"decisions": []}] * 10)
    metadata_provider = FakeGenerationProvider()
    service = IngestionService(
        session=db_session,
        embedding_provider=embedding_provider,
        decision_extractor=DecisionExtractor(decision_provider),
        metadata_extractor=MetadataExtractor(metadata_provider),
        upload_directory=tmp_path / "uploads",
    )
    return service, document, embedding_provider


def write_source(tmp_path: Path, content: str) -> Path:
    source = tmp_path / "meeting.md"
    source.write_text(content, encoding="utf-8")
    return source


@pytest.mark.asyncio
async def test_unchanged_checksum_skips_new_version(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, _ = await create_harness(db_session, tmp_path)
    source = write_source(tmp_path, GOOD_CONTENT)

    first = await service.ingest(document.id, source, request_id="request-1")
    repeated = await service.ingest(document.id, source, request_id="request-2")

    count = await db_session.scalar(
        select(func.count(DocumentVersion.id)).where(
            DocumentVersion.document_id == document.id
        )
    )
    assert repeated.skipped is True
    assert repeated.version_id == first.version_id
    assert count == 1


@pytest.mark.asyncio
async def test_successful_reindex_atomically_activates_new_version(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, _ = await create_harness(db_session, tmp_path)
    source = write_source(tmp_path, GOOD_CONTENT)
    first = await service.ingest(document.id, source, request_id="request-1")
    write_source(tmp_path, CHANGED_CONTENT)

    second = await service.ingest(document.id, source, request_id="request-2")
    await db_session.refresh(document)
    versions = list(
        await db_session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number)
        )
    )

    assert second.skipped is False
    assert document.active_version_id == second.version_id
    assert [(version.id, version.state) for version in versions] == [
        (first.version_id, "retired"),
        (second.version_id, "active"),
    ]
    assert await db_session.scalar(
        select(func.count(Passage.id)).where(
            Passage.document_version_id == second.version_id
        )
    )
    job = await db_session.scalar(
        select(IngestionJob).where(IngestionJob.document_version_id == second.version_id)
    )
    assert job is not None
    assert job.status == "completed"
    assert job.progress == 100


@pytest.mark.asyncio
async def test_failed_reindex_keeps_previous_version_active(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, embedding_provider = await create_harness(db_session, tmp_path)
    source = write_source(tmp_path, GOOD_CONTENT)
    first = await service.ingest(document.id, source, request_id="request-1")
    write_source(tmp_path, CHANGED_CONTENT)
    embedding_provider.fail_next()

    with pytest.raises(ProviderUnavailable):
        await service.ingest(document.id, source, request_id="request-2")

    await db_session.refresh(document)
    versions = list(
        await db_session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number)
        )
    )
    assert document.active_version_id == first.version_id
    assert [version.state for version in versions] == ["active", "failed"]
    assert versions[1].error == {"code": "provider_unavailable"}
    failed_job = await db_session.scalar(
        select(IngestionJob).where(
            IngestionJob.document_version_id == versions[1].id
        )
    )
    assert failed_job is not None
    assert failed_job.status == "failed"


@pytest.mark.asyncio
async def test_reindex_retires_extracted_decisions_and_reviews_corrections(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, _ = await create_harness(db_session, tmp_path)
    source = write_source(tmp_path, GOOD_CONTENT)
    first = await service.ingest(document.id, source, request_id="request-1")
    extracted = Decision(
        document_version_id=first.version_id,
        statement="Extracted decision",
        status="active",
        provenance="extracted",
        review_state="supported",
        user_edited=False,
        retired=False,
    )
    corrected = Decision(
        document_version_id=first.version_id,
        statement="Corrected decision",
        status="active",
        provenance="user_corrected",
        review_state="supported",
        user_edited=True,
        retired=False,
    )
    db_session.add_all([extracted, corrected])
    await db_session.flush()
    write_source(tmp_path, CHANGED_CONTENT)

    await service.ingest(document.id, source, request_id="request-2")
    await db_session.refresh(extracted)
    await db_session.refresh(corrected)

    assert extracted.retired is True
    assert corrected.retired is False
    assert corrected.review_state == "needs_review"
