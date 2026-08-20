from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion import service as ingestion_service_module
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.models import (
    Decision,
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
    Workspace,
)
from decision_assistant.providers.base import EmbeddingPurpose, ProviderUnavailable
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.workspace.service import WorkspaceService
from decision_assistant.workspace.embedding_profile import CorpusResetRequired

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
    *,
    retrieval_unit_strategy: str = "passage_hybrid",
) -> tuple[IngestionService, Document, FakeEmbeddingProvider]:
    workspace = await WorkspaceService(db_session).get_or_create_active(
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
        retrieval_unit_strategy=retrieval_unit_strategy,  # type: ignore[arg-type]
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
    workspace = await db_session.get(Workspace, document.workspace_id)
    assert workspace is not None
    await db_session.refresh(workspace)
    assert workspace.knowledge_revision == 2


@pytest.mark.asyncio
async def test_new_passages_store_the_validated_embedding_profile(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, embedding_provider = await create_harness(db_session, tmp_path)

    result = await service.ingest(
        document.id,
        write_source(tmp_path, GOOD_CONTENT),
        request_id="profile-request",
    )
    passages = list(
        await db_session.scalars(
            select(Passage).where(Passage.document_version_id == result.version_id)
        )
    )

    assert passages
    expected_profile = {
        "provider": embedding_provider.profile.provider,
        "model": embedding_provider.profile.model,
        "dimension": embedding_provider.profile.dimension,
        "adapter_config_version": embedding_provider.profile.adapter_config_version,
    }
    assert all(passage.embedding_profile == expected_profile for passage in passages)
    workspace = await db_session.get(Workspace, document.workspace_id)
    assert workspace is not None
    assert workspace.embedding_profile == expected_profile


@pytest.mark.asyncio
async def test_new_passages_store_structural_metadata(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, _ = await create_harness(db_session, tmp_path)

    result = await service.ingest(
        document.id,
        write_source(tmp_path, GOOD_CONTENT),
        request_id="structural-request",
    )
    passages = list(
        await db_session.scalars(
            select(Passage).where(Passage.document_version_id == result.version_id)
        )
    )

    assert passages
    for passage in passages:
        metadata = passage.structural_metadata
        assert isinstance(metadata, dict)
        assert "group_path" in metadata
        assert isinstance(metadata["group_path"], list)
        assert "block_types" in metadata
        # Deterministic: block_types is sorted and unique.
        assert metadata["block_types"] == sorted(set(metadata["block_types"]))

    # The heading chunk carries heading + paragraph block types with a group path.
    heading_chunks = [
        passage
        for passage in passages
        if "heading" in passage.structural_metadata["block_types"]
    ]
    assert heading_chunks
    assert all(passage.structural_metadata["group_path"] for passage in heading_chunks)
    assert any(
        "paragraph" in passage.structural_metadata["block_types"]
        for passage in passages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "decision_kind"),
    [
        ("sentence_expanded", "sentence"),
        ("parent_child_merged", "parent"),
    ],
)
async def test_sentence_based_strategies_persist_linked_parent_and_sentence_units(
    db_session: AsyncSession,
    tmp_path: Path,
    strategy: str,
    decision_kind: str,
) -> None:
    service, document, embedding_provider = await create_harness(
        db_session,
        tmp_path,
        retrieval_unit_strategy=strategy,
    )
    source = write_source(
        tmp_path,
        GOOD_CONTENT + "\nThe import flow needs deterministic regression coverage.\n",
    )

    result = await service.ingest(document.id, source, request_id=strategy)
    passages = list(
        await db_session.scalars(
            select(Passage)
            .where(Passage.document_version_id == result.version_id)
            .order_by(Passage.sequence_number)
        )
    )
    parents = [passage for passage in passages if passage.retrieval_unit_kind == "parent"]
    sentences = [
        passage for passage in passages if passage.retrieval_unit_kind == "sentence"
    ]

    assert parents
    assert len(sentences) >= 2
    assert all(sentence.parent_passage_id in {parent.id for parent in parents} for sentence in sentences)
    assert all("sentence_index" in sentence.structural_metadata for sentence in sentences)
    assert embedding_provider.purposes == [EmbeddingPurpose.DOCUMENT]
    assert all(passage.retrieval_unit_kind != "passage" for passage in passages)
    assert decision_kind in {"sentence", "parent"}


@pytest.mark.asyncio
async def test_provider_change_does_not_defeat_checksum_idempotency(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, embedding_provider = await create_harness(db_session, tmp_path)
    source = write_source(tmp_path, GOOD_CONTENT)
    first = await service.ingest(document.id, source, request_id="provider-before")
    original_profile = embedding_provider.profile.as_dict()
    embedding_provider._profile = replace(  # type: ignore[attr-defined]
        embedding_provider.profile,
        model="changed-embedding-model",
    )

    repeated = await service.ingest(
        document.id,
        source,
        request_id="provider-after",
    )

    assert repeated.skipped is True
    assert repeated.version_id == first.version_id
    assert await db_session.scalar(
        select(func.count(DocumentVersion.id)).where(
            DocumentVersion.document_id == document.id
        )
    ) == 1
    workspace = await db_session.get(Workspace, document.workspace_id)
    assert workspace is not None
    assert workspace.embedding_profile == original_profile


@pytest.mark.asyncio
async def test_ingestion_uses_workspace_embedding_guard_before_activation(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, document, _ = await create_harness(db_session, tmp_path)
    acquired_for: list[object] = []
    original = ingestion_service_module.acquire_workspace_embedding_lock

    async def recording_guard(session: AsyncSession, workspace_id: object) -> None:
        acquired_for.append(workspace_id)
        await original(session, workspace_id)  # type: ignore[arg-type]

    monkeypatch.setattr(
        ingestion_service_module,
        "acquire_workspace_embedding_lock",
        recording_guard,
    )

    await service.ingest(
        document.id,
        write_source(tmp_path, GOOD_CONTENT),
        request_id="guard-request",
    )

    assert acquired_for == [document.workspace_id]


@pytest.mark.asyncio
async def test_waiting_old_profile_ingestion_cannot_activate_mixed_corpus(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, embedding_provider = await create_harness(db_session, tmp_path)
    source = write_source(tmp_path, GOOD_CONTENT)
    first = await service.ingest(document.id, source, request_id="old-active")
    migrated_profile = replace(
        embedding_provider.profile,
        model="new-embedding-model",
    ).as_dict()
    workspace = await db_session.get(Workspace, document.workspace_id)
    assert workspace is not None
    workspace.embedding_profile = migrated_profile
    active_passages = list(
        await db_session.scalars(
            select(Passage).where(Passage.document_version_id == first.version_id)
        )
    )
    for passage in active_passages:
        passage.embedding_profile = migrated_profile
    await db_session.flush()
    write_source(tmp_path, CHANGED_CONTENT)

    with pytest.raises(CorpusResetRequired) as error:
        await service.ingest(document.id, source, request_id="queued-old-provider")

    await db_session.refresh(document)
    await db_session.refresh(workspace)
    versions = list(
        await db_session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number)
        )
    )
    searchable_profiles = list(
        await db_session.scalars(
            select(Passage.embedding_profile)
            .join(
                DocumentVersion,
                DocumentVersion.id == Passage.document_version_id,
            )
            .where(DocumentVersion.state == "active")
        )
    )
    assert error.value.code == "corpus_reset_required"
    assert document.active_version_id == first.version_id
    assert [version.state for version in versions] == ["active", "failed"]
    assert workspace.embedding_profile == migrated_profile
    assert searchable_profiles
    assert all(profile == migrated_profile for profile in searchable_profiles)


@pytest.mark.asyncio
async def test_successful_reindex_atomically_activates_new_version(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service, document, embedding_provider = await create_harness(
        db_session, tmp_path
    )
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
    assert embedding_provider.purposes == [
        EmbeddingPurpose.DOCUMENT,
        EmbeddingPurpose.DOCUMENT,
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
