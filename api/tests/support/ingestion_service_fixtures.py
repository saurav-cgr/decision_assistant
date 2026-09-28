"""Shared scaffolding for `test_ingestion_service.py` (DB53).

Extracted so the test module stays under AGENTS.md's 500-line cap for hand-written files; DB30 and
DB49 set the same precedent (`tests/support/`). These are plain functions rather than fixtures
because each test wants its own document, workspace and provider wiring.
"""

from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.models import Document
from decision_assistant.ingestion.service import IngestionService
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
