"""Shared corpus scaffolding for the hybrid-retrieval tests (DB53).

Extracted from `test_hybrid_retrieval.py` so that file and
`test_hybrid_retrieval_decisions.py` stay under AGENTS.md's 500-line cap for hand-written files;
DB30 and DB49 set the same precedent (`tests/support/`).
"""

from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    EmbeddingCache,
    Passage,
)
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.workspace.embedding_profile import embedding_profile_fingerprint
from decision_assistant.workspace.models import Workspace

EMBEDDING_PROFILE = FakeEmbeddingProvider(dimension=768).profile.as_dict()


async def create_workspace(session: AsyncSession) -> Workspace:
    workspace = Workspace(
        name=f"Retrieval {uuid4()}",
        embedding_profile=EMBEDDING_PROFILE,
    )
    session.add(workspace)
    await session.flush()
    return workspace


async def create_version(
    session: AsyncSession,
    workspace: Workspace,
    *,
    name: str,
    state: str = "active",
    media_type: str = "text/markdown",
    project: str = "Atlas",
    document_date: date = date(2026, 7, 15),
    participants: list[str] | None = None,
) -> tuple[Document, DocumentVersion]:
    document = Document(
        workspace_id=workspace.id,
        display_name=name,
        media_type=media_type,
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        title=name,
        document_date=document_date,
        participants=participants or [],
        source_type="meeting",
        project=project,
        checksum=sha256(name.encode()).hexdigest(),
        storage_path=f"fixtures/{name}",
        normalized_content="",
        chunking_profile=CURRENT_CHUNKING_PROFILE,
        state=state,
    )
    session.add(version)
    await session.flush()
    if state == "active":
        document.active_version_id = version.id
        await session.flush()
    return document, version


async def create_passage(
    session: AsyncSession,
    version: DocumentVersion,
    *,
    sequence_number: int,
    content: str,
    embedding: list[float],
    retrieval_unit_kind: str = "passage",
    parent_passage_id: UUID | None = None,
) -> Passage:
    passage = Passage(
        document_version_id=version.id,
        sequence_number=sequence_number,
        content=content,
        start_offset=0,
        end_offset=len(content),
        content_hash=sha256(content.encode()).hexdigest(),
        locator={"kind": "lines", "start": sequence_number + 1, "end": sequence_number + 1},
        embedding=embedding,
        embedding_profile=EMBEDDING_PROFILE,
        retrieval_unit_kind=retrieval_unit_kind,
        parent_passage_id=parent_passage_id,
    )
    session.add(passage)
    await session.flush()
    document = await session.get(Document, version.document_id)
    assert document is not None
    cache = await session.scalar(
        select(EmbeddingCache).where(
            EmbeddingCache.workspace_id == document.workspace_id,
            EmbeddingCache.content_hash == passage.content_hash,
            EmbeddingCache.embedding_profile_fingerprint
            == embedding_profile_fingerprint(EMBEDDING_PROFILE),
        )
    )
    if cache is None:
        cache = EmbeddingCache(
            workspace_id=document.workspace_id,
            content_hash=passage.content_hash,
            embedding_profile_fingerprint=embedding_profile_fingerprint(
                EMBEDDING_PROFILE
            ),
            embedding_profile=EMBEDDING_PROFILE,
            embedding=embedding,
        )
        session.add(cache)
        await session.flush()
    passage.embedding_cache_id = cache.id
    await session.flush()
    return passage
