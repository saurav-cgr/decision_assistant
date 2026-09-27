"""T028/T031: `run_corpus_rebuild` re-dispatches ingestion and re-links decisions.

A rebuild must (1) not duplicate decisions — the existing pipeline extracts
decisions on every ingest, so the rebuild redispatch passes
`extract_decisions=False` and the preserved decision stays the sole record
(DB40 human decision); (2) re-link a preserved decision's
`document_version_id` to the new active version for its (identity-preserved)
document; (3) re-link `decision_evidence.passage_id` when an identical
`content_hash` chunk survives re-chunking, and otherwise set
`citation_stale = true` rather than leaving a dangling guess.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
)
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import FakeEmbeddingProvider, FakeGenerationProvider
from decision_assistant.config import Settings
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.rebuild.coordinator import run_corpus_rebuild

_METADATA_RESPONSE = {
    "title": "Architecture Sync",
    "document_date": "2026-07-15",
    "participants": ["Maya", "Ravi"],
    "source_type": "meeting",
    "project": "Atlas",
}

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

_QUOTED_SENTENCE = "Authentication was postponed until the import flow is stable."


async def _seed_document_with_decision(
    session: AsyncSession, upload_directory: Path
) -> tuple[object, object, object]:
    """Ingest a real document (so passage content_hash values are genuine
    chunker output, not fabricated) with decision extraction skipped, then
    hand-attach a Decision/DecisionEvidence to its first passage — standing
    in for a decision the original (non-rebuild) pipeline would have
    extracted from that same chunk."""
    workspace = Workspace(id=uuid4(), name=f"Rebuild run {uuid4()}")
    session.add(workspace)
    await session.flush()

    document_id = uuid4()
    document = Document(
        id=document_id,
        workspace_id=workspace.id,
        display_name="meeting.md",
        media_type="text/markdown",
    )
    session.add(document)
    await session.flush()

    source_path = upload_directory.parent / "source" / "meeting.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(GOOD_CONTENT, encoding="utf-8")

    service = IngestionService(
        session=session,
        embedding_provider=FakeEmbeddingProvider(dimension=768),
        decision_extractor=DecisionExtractor(FakeGenerationProvider()),
        metadata_extractor=MetadataExtractor(FakeGenerationProvider([_METADATA_RESPONSE])),
        upload_directory=upload_directory,
    )
    result = await service.ingest(
        document_id,
        source_path,
        request_id=str(uuid4()),
        job_id=None,
        extract_decisions=False,
    )
    await session.flush()

    passages = list(
        await session.scalars(
            select(Passage).where(Passage.document_version_id == result.version_id)
        )
    )
    passage = next(
        (p for p in passages if _QUOTED_SENTENCE in p.content), None
    )
    assert passage is not None, [p.content for p in passages]
    start_offset = passage.content.find(_QUOTED_SENTENCE)

    decision = Decision(
        workspace_id=workspace.id,
        document_version_id=result.version_id,
        statement="Authentication was postponed.",
        status="active",
        provenance="extracted",
        review_state="supported",
    )
    session.add(decision)
    await session.flush()

    evidence = DecisionEvidence(
        decision_id=decision.id,
        passage_id=passage.id,
        start_offset=start_offset,
        end_offset=start_offset + len(_QUOTED_SENTENCE),
        content_hash=passage.content_hash,
        quote=_QUOTED_SENTENCE,
    )
    session.add(evidence)
    await session.flush()

    return workspace, document, decision


@pytest.mark.asyncio
async def test_rebuild_relinks_decision_when_chunk_content_hash_survives(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    upload_directory = tmp_path / "uploads"
    workspace, document, decision = await _seed_document_with_decision(
        db_session, upload_directory
    )
    decisions_before = list(
        await db_session.scalars(
            select(Decision).where(Decision.workspace_id == workspace.id)
        )
    )
    assert len(decisions_before) == 1
    original_document_version_id = decision.document_version_id

    settings = Settings(upload_directory=upload_directory)
    providers = ProviderBundle(
        embedding=FakeEmbeddingProvider(dimension=768),
        generation=FakeGenerationProvider(
            [
                {
                    "title": "Architecture Sync",
                    "document_date": "2026-07-15",
                    "participants": ["Maya", "Ravi"],
                    "source_type": "meeting",
                    "project": "Atlas",
                }
            ]
        ),
    )

    rebuild = await run_corpus_rebuild(
        db_session,
        workspace_id=workspace.id,
        reason="chunking_profile_changed",
        settings=settings,
        providers=providers,
        request_id=str(uuid4()),
    )

    assert rebuild.status == "completed", rebuild.error
    assert rebuild.documents_total == 1
    assert rebuild.documents_completed == 1

    reloaded_decision = await db_session.get(Decision, decision.id)
    assert reloaded_decision is not None
    assert reloaded_decision.document_version_id is not None
    assert reloaded_decision.document_version_id != original_document_version_id

    new_version = await db_session.get(DocumentVersion, reloaded_decision.document_version_id)
    assert new_version is not None
    assert new_version.document_id == document.id

    reloaded_evidence = await db_session.scalar(
        select(DecisionEvidence).where(DecisionEvidence.decision_id == decision.id)
    )
    assert reloaded_evidence.passage_id is not None
    assert reloaded_evidence.citation_stale is False
    assert reloaded_evidence.quote == _QUOTED_SENTENCE

    # A rebuild must not re-extract decisions: still exactly one decision.
    decisions_after = list(
        await db_session.scalars(
            select(Decision).where(Decision.workspace_id == workspace.id)
        )
    )
    assert len(decisions_after) == 1


@pytest.mark.asyncio
async def test_rebuild_marks_citation_stale_when_chunk_hash_changes(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    upload_directory = tmp_path / "uploads"
    workspace, document, decision = await _seed_document_with_decision(
        db_session, upload_directory
    )
    # Rewrite the stored source (after seeding the original passage/evidence
    # content_hash) so re-chunking produces a different hash for the sentence
    # the evidence pointed at, simulating a chunking-profile change that
    # reshapes chunk boundaries.
    active_version = await db_session.get(DocumentVersion, decision.document_version_id)
    (upload_directory / active_version.storage_path).write_text(
        GOOD_CONTENT.replace(
            "Authentication was postponed until the import flow is stable.",
            "Authentication has been postponed until the import flow stabilizes.",
        ),
        encoding="utf-8",
    )

    settings = Settings(upload_directory=upload_directory)
    providers = ProviderBundle(
        embedding=FakeEmbeddingProvider(dimension=768),
        generation=FakeGenerationProvider(
            [
                {
                    "title": "Architecture Sync",
                    "document_date": "2026-07-15",
                    "participants": ["Maya", "Ravi"],
                    "source_type": "meeting",
                    "project": "Atlas",
                }
            ]
        ),
    )

    rebuild = await run_corpus_rebuild(
        db_session,
        workspace_id=workspace.id,
        reason="chunking_profile_changed",
        settings=settings,
        providers=providers,
        request_id=str(uuid4()),
    )

    assert rebuild.status == "completed"

    reloaded_decision = await db_session.get(Decision, decision.id)
    assert reloaded_decision.document_version_id is not None

    reloaded_evidence = await db_session.scalar(
        select(DecisionEvidence).where(DecisionEvidence.decision_id == decision.id)
    )
    assert reloaded_evidence.passage_id is None
    assert reloaded_evidence.citation_stale is True
    # The quote itself is still the record of what the decision was extracted
    # from, even though the source text it referred to no longer exists (DB40).
    assert reloaded_evidence.quote == _QUOTED_SENTENCE


@pytest.mark.asyncio
async def test_rebuild_relinks_reshaped_chunk_by_quote_text(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """DB40's residual gap: the chunk hash changes but the quote survives.

    A chunking-profile change reshapes chunk boundaries far more often than it
    changes text, so matching whole-chunk `content_hash` values alone drops
    evidence the new corpus still contains verbatim. The evidence row's stored
    quote is the stable identity; re-linking by it keeps the decision visible
    to the readers that inner-join on `Passage`.
    """
    upload_directory = tmp_path / "uploads"
    workspace, document, decision = await _seed_document_with_decision(
        db_session, upload_directory
    )
    original_evidence = await db_session.scalar(
        select(DecisionEvidence).where(DecisionEvidence.decision_id == decision.id)
    )
    original_hash = original_evidence.content_hash
    active_version = await db_session.get(DocumentVersion, decision.document_version_id)
    (upload_directory / active_version.storage_path).write_text(
        GOOD_CONTENT.replace(
            _QUOTED_SENTENCE,
            f"The import flow ships first. {_QUOTED_SENTENCE}",
        ),
        encoding="utf-8",
    )

    rebuild = await run_corpus_rebuild(
        db_session,
        workspace_id=workspace.id,
        reason="chunking_profile_changed",
        settings=Settings(upload_directory=upload_directory),
        providers=ProviderBundle(
            embedding=FakeEmbeddingProvider(dimension=768),
            generation=FakeGenerationProvider(
                [
                    {
                        "title": "Architecture Sync",
                        "document_date": "2026-07-15",
                        "participants": ["Maya", "Ravi"],
                        "source_type": "meeting",
                        "project": "Atlas",
                    }
                ]
            ),
        ),
        request_id=str(uuid4()),
    )

    assert rebuild.status == "completed", rebuild.error

    reloaded_decision = await db_session.get(Decision, decision.id)
    new_version_id = reloaded_decision.document_version_id
    new_hashes = set(
        await db_session.scalars(
            select(Passage.content_hash).where(
                Passage.document_version_id == new_version_id
            )
        )
    )
    assert original_hash not in new_hashes, (
        "the fixture must force the quote-matching path, not the content_hash one"
    )

    reloaded_evidence = await db_session.scalar(
        select(DecisionEvidence).where(DecisionEvidence.decision_id == decision.id)
    )
    assert reloaded_evidence.passage_id is not None
    assert reloaded_evidence.citation_stale is False
    assert reloaded_evidence.quote == _QUOTED_SENTENCE

    matched_passage = await db_session.get(Passage, reloaded_evidence.passage_id)
    assert matched_passage is not None
    assert matched_passage.document_version_id == new_version_id
    assert _QUOTED_SENTENCE in matched_passage.content
    # The row stays coherent with the passage it now points at (the correction
    # API rejects a hash that does not match the passage).
    assert reloaded_evidence.content_hash == matched_passage.content_hash


@pytest.mark.asyncio
async def test_rebuild_preserves_document_without_active_version(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """DB42: a failed document survives the rebuild with its retry path intact."""
    workspace_id = uuid4()
    document_id = uuid4()
    db_session.add(Workspace(id=workspace_id, name=f"Failed doc {workspace_id}"))
    await db_session.flush()
    db_session.add(
        Document(
            id=document_id,
            workspace_id=workspace_id,
            display_name="broken.pdf",
            media_type="application/pdf",
        )
    )
    await db_session.flush()
    failed_version = DocumentVersion(
        document_id=document_id,
        version_number=1,
        checksum="c" * 64,
        storage_path="broken.pdf",
        state="failed",
        error={"code": "pdf_parse_failed"},
    )
    db_session.add(failed_version)
    await db_session.flush()
    job = IngestionJob(
        document_id=document_id,
        document_version_id=failed_version.id,
        request_id=str(uuid4()),
    )
    db_session.add(job)
    await db_session.flush()

    rebuild = await run_corpus_rebuild(
        db_session,
        workspace_id=workspace_id,
        reason="corpus_reset_required",
        settings=Settings(upload_directory=tmp_path / "uploads"),
        providers=ProviderBundle(
            embedding=FakeEmbeddingProvider(dimension=768),
            generation=FakeGenerationProvider(),
        ),
        request_id=str(uuid4()),
    )

    assert rebuild.status == "completed"
    # The failed document is not re-ingestable, so it is not part of the plan.
    assert rebuild.documents_total == 0
    assert await db_session.get(Document, document_id) is not None
    assert await db_session.get(DocumentVersion, failed_version.id) is not None
    assert await db_session.get(IngestionJob, job.id) is not None
