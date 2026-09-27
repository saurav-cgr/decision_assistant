"""Read model for the document API: the list and the detail response.

Split out of `documents/service.py` (DB67) so that file keeps the write path — upload, the
disclosure gate, retry and dispatch — and this one owns the two queries that only read. Behaviour is
unchanged: `DocumentService.list_documents`/`get_document` delegate here so the route and every
existing caller keep their signatures.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.models import Decision
from decision_assistant.documents.errors import DocumentApiError
from decision_assistant.documents.schemas import (
    ActiveVersionDetail,
    DocumentDetail,
    DocumentListItem,
    DocumentListResponse,
    PassageDetail,
)
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
)


async def list_document_items(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
) -> DocumentListResponse:
    # `id` (descending UUID) is the tiebreaker: `created_at`'s server default
    # is `now()`, which is the TRANSACTION timestamp, so documents created in
    # one transaction (a multi-file upload, a corpus rebuild that re-creates
    # every document — DB48) all share it. Without the tiebreaker this list
    # has no defined order for them. `Document.id` is stable for a
    # document's whole life, including across a rebuild, which preserves the
    # id, so ties resolve the same way before and after one.
    statement = select(Document).order_by(
        Document.created_at.desc(), Document.id.desc()
    )
    if workspace_id is not None:
        statement = statement.where(Document.workspace_id == workspace_id)
    documents = list(await session.scalars(statement))
    items: list[DocumentListItem] = []
    for document in documents:
        job = await session.scalar(
            select(IngestionJob)
            .where(IngestionJob.document_id == document.id)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .limit(1)
        )
        version = (
            await session.get(DocumentVersion, document.active_version_id)
            if document.active_version_id is not None
            else None
        )
        decision_count = (
            await session.scalar(
                select(func.count())
                .select_from(Decision)
                .where(
                    Decision.document_version_id == version.id,
                    Decision.retired.is_(False),
                )
            )
            if version is not None
            else 0
        )
        modification_state = None
        if job is not None and job.stage == "unchanged":
            modification_state = "unchanged"
        elif version is not None:
            modification_state = "modified" if version.version_number > 1 else "new"
        items.append(
            DocumentListItem(
                id=document.id,
                display_name=document.display_name,
                media_type=document.media_type,
                active_version_id=document.active_version_id,
                status=job.status if job is not None else None,
                stage=job.stage if job is not None else None,
                progress=job.progress if job is not None else None,
                error=job.error if job is not None else None,
                title=version.title if version is not None else None,
                document_date=version.document_date if version is not None else None,
                participants=version.participants if version is not None else [],
                source_type=version.source_type if version is not None else None,
                project=version.project if version is not None else None,
                modification_state=modification_state,
                decision_count=decision_count or 0,
            )
        )
    return DocumentListResponse(items=items)


async def get_document_detail(
    session: AsyncSession,
    document_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> DocumentDetail:
    document = await session.get(Document, document_id)
    if document is None or (
        workspace_id is not None and document.workspace_id != workspace_id
    ):
        raise DocumentApiError("document_not_found", "Document not found", 404)

    version = (
        await session.get(DocumentVersion, document.active_version_id)
        if document.active_version_id is not None
        else None
    )
    passages = (
        list(
            await session.scalars(
                select(Passage)
                .where(Passage.document_version_id == version.id)
                .order_by(Passage.sequence_number)
            )
        )
        if version is not None
        else []
    )
    job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.document_id == document.id)
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
        .limit(1)
    )
    return DocumentDetail(
        id=document.id,
        display_name=document.display_name,
        media_type=document.media_type,
        status=job.status if job is not None else None,
        stage=job.stage if job is not None else None,
        progress=job.progress if job is not None else None,
        error=job.error if job is not None else None,
        active_version=(
            ActiveVersionDetail(
                id=version.id,
                version_number=version.version_number,
                title=version.title,
                document_date=version.document_date,
                participants=version.participants,
                source_type=version.source_type,
                project=version.project,
                state=version.state,
            )
            if version is not None
            else None
        ),
        passages=[
            PassageDetail(
                sequence_number=passage.sequence_number,
                content=passage.content,
                locator=passage.locator,
                structural_metadata=passage.structural_metadata,
            )
            for passage in passages
        ],
    )
