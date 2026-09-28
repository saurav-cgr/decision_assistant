"""DB48: a successful rebuild must not re-order the document list.

`documents.service.list_documents` orders by `Document.created_at DESC`. A
corpus rebuild deletes and re-creates every active `Document` row with the SAME
id, and `created_at` is a `server_default` of `func.now()` — which in PostgreSQL
is the TRANSACTION timestamp. The whole rebuild is one transaction, so before
this fix every re-created row carried a byte-identical timestamp: the list lost
its only sort key and came back in whatever order the plan happened to produce.
That is the human-reported symptom ("the document list comes back in a different
order after a successful rebuild"); the same root cause also made every document
read as uploaded just now.

The remedy has two halves, and the tests below cover both:

1. `snapshot_workspace` captures `created_at` and `execute_rebuild` writes it
   onto the re-created row, so the order *survives* the rebuild.
2. `list_documents` breaks ties on `Document.id DESC`, so documents that
   genuinely share a `created_at` (a multi-file upload commits them in one
   transaction, exactly like a rebuild) have a defined order instead of an
   arbitrary one.

`test_rebuild_preserves_document_list_order` is the end-to-end claim, with the
documents' newest-first order deliberately the reverse of their insertion order
so that "it looks the same" cannot pass by coinciding with heap order. The
second test pins the tiebreaker itself and needs no ingestion or rebuild, which
keeps it a fast, single-purpose guard.
"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.documents.service import DocumentService
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.models import Document
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.rebuild.coordinator import run_corpus_rebuild

_METADATA_RESPONSE = {
    "title": "Architecture Sync",
    "document_date": "2026-07-15",
    "participants": ["Maya", "Ravi"],
    "source_type": "meeting",
    "project": "Atlas",
}

# Two clearly separated timestamps: the list is newest-first, so the expected
# order is [_NEWER, _OLDER] while insertion order is [_OLDER, _NEWER].
_OLDER = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
_NEWER = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)

_CONTENT = """---
title: Authentication rollout
date: 2026-07-15
participants: [Maya, Ravi]
source_type: meeting
project: Atlas
---

# Authentication

Authentication was postponed until the import flow is stable.
"""


class _NoopDispatcher:
    """`list_documents` never dispatches; the service only needs the attribute."""

    async def dispatch(self, **_: object) -> None:
        raise AssertionError("list_documents must not dispatch ingestion")


async def _seed_document(
    session: AsyncSession,
    workspace: Workspace,
    upload_directory: Path,
    *,
    display_name: str,
    created_at: datetime,
) -> Document:
    """Ingest one real document through the normal pipeline.

    A rebuild only re-ingests documents that have an active version (DB42), so
    the rows have to go through `IngestionService` rather than being inserted
    directly.
    """
    document = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        display_name=display_name,
        media_type="text/markdown",
        created_at=created_at,
    )
    session.add(document)
    await session.flush()

    source_path = upload_directory.parent / "source" / display_name
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(_CONTENT, encoding="utf-8")

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
        document.id,
        source_path,
        request_id=str(uuid4()),
        job_id=None,
        extract_decisions=False,
    )
    await session.flush()
    return document


async def _list_document_ids(
    session: AsyncSession, upload_directory: Path, workspace_id: UUID
) -> list[UUID]:
    service = DocumentService(
        session=session,
        settings=Settings(upload_directory=upload_directory),
        dispatcher=_NoopDispatcher(),
    )
    response = await service.list_documents(workspace_id=workspace_id)
    return [item.id for item in response.items]


@pytest.mark.asyncio
async def test_rebuild_preserves_document_list_order(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    upload_directory = tmp_path / "uploads"
    workspace = Workspace(id=uuid4(), name=f"Rebuild order {uuid4()}")
    db_session.add(workspace)
    await db_session.flush()

    older = await _seed_document(
        db_session,
        workspace,
        upload_directory,
        display_name="auth-rollout.md",
        created_at=_OLDER,
    )
    newer = await _seed_document(
        db_session,
        workspace,
        upload_directory,
        display_name="security-notes.md",
        created_at=_NEWER,
    )

    before = await _list_document_ids(db_session, upload_directory, workspace.id)
    assert before == [newer.id, older.id], (
        "the fixture is only meaningful if the list is newest-first, i.e. the "
        f"reverse of the insertion order: {before}"
    )

    # One metadata response per document; extras are harmless.
    providers = ProviderBundle(
        embedding=FakeEmbeddingProvider(dimension=768),
        generation=FakeGenerationProvider([_METADATA_RESPONSE] * 4),
    )
    rebuild = await run_corpus_rebuild(
        db_session,
        workspace_id=workspace.id,
        reason="chunking_profile_changed",
        settings=Settings(upload_directory=upload_directory),
        providers=providers,
        request_id=str(uuid4()),
    )
    assert rebuild.status == "completed", rebuild.error
    assert rebuild.documents_completed == 2

    # The re-created rows carry the original timestamps. This is the root cause
    # and it is a deterministic assertion: before the fix both rows held the
    # transaction's `now()`, which cannot equal either seeded value.
    reloaded_older = await db_session.get(Document, older.id)
    reloaded_newer = await db_session.get(Document, newer.id)
    assert reloaded_older is not None
    assert reloaded_newer is not None
    assert reloaded_older.created_at == _OLDER
    assert reloaded_newer.created_at == _NEWER

    after = await _list_document_ids(db_session, upload_directory, workspace.id)
    assert after == before


@pytest.mark.asyncio
async def test_list_documents_breaks_created_at_ties_by_id(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Documents that share a `created_at` still have a defined order.

    A multi-file upload commits every document in one transaction, so their
    `created_at` values are identical and `ORDER BY created_at DESC` alone
    leaves the order to the plan. Insertion order here is [low, high] while the
    documented order is `id DESC`, so an unspecified order cannot pass.
    """
    upload_directory = tmp_path / "uploads"
    workspace = Workspace(id=uuid4(), name=f"List ties {uuid4()}")
    db_session.add(workspace)
    await db_session.flush()

    low = UUID("00000000-0000-0000-0000-0000000000a1")
    high = UUID("00000000-0000-0000-0000-0000000000a2")
    for document_id, display_name in ((low, "first.md"), (high, "second.md")):
        db_session.add(
            Document(
                id=document_id,
                workspace_id=workspace.id,
                display_name=display_name,
                media_type="text/markdown",
                created_at=_NEWER,
            )
        )
    await db_session.flush()

    assert await _list_document_ids(db_session, upload_directory, workspace.id) == [
        high,
        low,
    ]
