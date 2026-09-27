"""T026: a corpus rebuild's delete scope must match data-model.md exactly.

`truncate_corpus_derived_tables` must delete every corpus-derived row
(`documents, document_versions, passages, embedding_cache, ingestion_jobs`)
of the documents a rebuild can re-ingest, and must never delete `decisions`,
`decision_evidence`, or `retrieval_traces`. A document with no active version
is preserved entirely (DB42) — it cannot be re-ingested, so deleting it would
destroy its stored-file reference and retry path. `decisions`/`decision_evidence` survive with a nulled
`document_version_id`/`passage_id` (DB34, revision `0014_decision_setnull_fk`)
and, for `decisions`, a workspace-scoped `workspace_id` that never depended on
the corpus-derived chain in the first place (DB38, revision
`0015_decisions_workspace_id`). `retrieval_traces` is left untouched entirely
(DB37) — deleting it would cascade away `conversation_messages`/
`question_answers`.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    EmbeddingCache,
    IngestionJob,
    Passage,
)
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.rebuild.coordinator import (
    truncate_corpus_derived_tables,
)

_EMBEDDING = [0.0] * 768


async def _seed_corpus_and_decision(session: AsyncSession) -> tuple[object, object]:
    workspace_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    passage_id = uuid4()
    decision_id = uuid4()

    session.add(Workspace(id=workspace_id, name=f"Rebuild scope {workspace_id}"))
    await session.flush()

    session.add(
        Document(
            id=document_id,
            workspace_id=workspace_id,
            display_name="minutes.md",
            media_type="text/markdown",
        )
    )
    await session.flush()

    session.add(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            checksum="chk",
            storage_path="minutes.md",
            state="active",
        )
    )
    await session.flush()
    # DB42: only a document with an active version is re-ingestable, so only
    # those are truncated and rebuilt. Point the document at its version.
    document = await session.get(Document, document_id)
    document.active_version_id = version_id
    await session.flush()

    session.add(
        Passage(
            id=passage_id,
            document_version_id=version_id,
            sequence_number=0,
            content="We will use Postgres.",
            start_offset=0,
            end_offset=22,
            content_hash="hash",
            locator={"kind": "line", "line": 1},
            embedding=_EMBEDDING,
        )
    )
    session.add(
        IngestionJob(document_id=document_id, request_id=str(uuid4())),
    )
    session.add(
        EmbeddingCache(
            workspace_id=workspace_id,
            content_hash="hash",
            embedding_profile_fingerprint="fp",
            embedding_profile={"name": "test", "dimension": 768},
            embedding=_EMBEDDING,
        )
    )
    session.add(
        RetrievalTrace(
            workspace_id=workspace_id,
            request_id=str(uuid4()),
            normalized_question="what database?",
        )
    )
    await session.flush()

    session.add(
        Decision(
            id=decision_id,
            workspace_id=workspace_id,
            document_version_id=version_id,
            statement="Use Postgres.",
            status="active",
            provenance="extracted",
            review_state="supported",
        )
    )
    await session.flush()

    session.add(
        DecisionEvidence(
            decision_id=decision_id,
            passage_id=passage_id,
            start_offset=0,
            end_offset=22,
            content_hash="hash",
        )
    )
    await session.flush()

    return workspace_id, decision_id


async def _deleted_scope_counts(session: AsyncSession, workspace_id: object) -> dict[str, int]:
    return {
        "documents": await session.scalar(
            select(func.count(Document.id)).where(Document.workspace_id == workspace_id)
        ),
        "document_versions": await session.scalar(
            select(func.count(DocumentVersion.id)).select_from(DocumentVersion).join(
                Document, Document.id == DocumentVersion.document_id
            ).where(Document.workspace_id == workspace_id)
        ),
        "passages": await session.scalar(
            select(func.count(Passage.id)).select_from(Passage).join(
                DocumentVersion, DocumentVersion.id == Passage.document_version_id
            ).join(Document, Document.id == DocumentVersion.document_id).where(
                Document.workspace_id == workspace_id
            )
        ),
        "ingestion_jobs": await session.scalar(
            select(func.count(IngestionJob.id)).select_from(IngestionJob).join(
                Document, Document.id == IngestionJob.document_id
            ).where(Document.workspace_id == workspace_id)
        ),
        "embedding_cache": await session.scalar(
            select(func.count(EmbeddingCache.id)).where(
                EmbeddingCache.workspace_id == workspace_id
            )
        ),
    }


@pytest.mark.asyncio
async def test_rebuild_deletes_only_corpus_derived_tables_and_spares_decisions(
    db_session: AsyncSession,
) -> None:
    workspace_id, decision_id = await _seed_corpus_and_decision(db_session)

    before = await _deleted_scope_counts(db_session, workspace_id)
    assert all(count == 1 for count in before.values()), before
    traces_before = await db_session.scalar(
        select(func.count(RetrievalTrace.id)).where(
            RetrievalTrace.workspace_id == workspace_id
        )
    )
    assert traces_before == 1

    await truncate_corpus_derived_tables(db_session, workspace_id)
    await db_session.flush()

    after = await _deleted_scope_counts(db_session, workspace_id)
    assert all(count == 0 for count in after.values()), after

    traces_after = await db_session.scalar(
        select(func.count(RetrievalTrace.id)).where(
            RetrievalTrace.workspace_id == workspace_id
        )
    )
    assert traces_after == 1, "retrieval_traces must survive a rebuild (DB37)"

    decision = await db_session.get(Decision, decision_id)
    assert decision is not None
    assert decision.workspace_id == workspace_id
    assert decision.document_version_id is None

    listed = list(
        await db_session.scalars(
            select(Decision.id).where(Decision.workspace_id == workspace_id)
        )
    )
    assert listed == [decision_id], "a rebuilt decision must stay workspace-listable (DB38)"

    evidence = await db_session.scalar(
        select(DecisionEvidence).where(DecisionEvidence.decision_id == decision_id)
    )
    assert evidence is not None
    assert evidence.passage_id is None


@pytest.mark.asyncio
async def test_rebuild_preserves_documents_without_an_active_version(
    db_session: AsyncSession,
) -> None:
    """DB42: a document whose ingestion failed must survive a rebuild.

    `_snapshot_workspace` can only re-ingest documents with an active version,
    so the truncate must leave the rest alone — deleting them would take the
    stored-file reference and the ingestion-job retry path with them, with
    nothing left to recreate them from (spec US3: documents survive the
    upgrade).
    """
    workspace_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()

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
    db_session.add(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            checksum="c" * 64,
            storage_path="broken.pdf",
            state="failed",
            error={"code": "pdf_parse_failed"},
        )
    )
    job = IngestionJob(
        document_id=document_id,
        document_version_id=version_id,
        request_id=str(uuid4()),
    )
    db_session.add(job)
    await db_session.flush()

    await truncate_corpus_derived_tables(
        db_session, workspace_id, preserve_document_ids=[document_id]
    )
    await db_session.flush()

    assert await db_session.get(Document, document_id) is not None
    assert await db_session.get(DocumentVersion, version_id) is not None
    assert await db_session.get(IngestionJob, job.id) is not None
