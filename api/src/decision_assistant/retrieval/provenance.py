from collections import defaultdict
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.models import Document, DocumentVersion, Passage
from decision_assistant.retrieval.schemas import EquivalentSource


async def load_equivalent_sources(
    session: AsyncSession,
    selected_ids: list[UUID],
    passage_by_id: dict[UUID, Passage],
    *,
    workspace_id: UUID,
) -> dict[UUID, list[EquivalentSource]]:
    selectors = [
        (
            (
                Passage.embedding_cache_id == passage.embedding_cache_id
                if passage.embedding_cache_id is not None
                else Passage.id == passage.id
            )
            & (Passage.retrieval_unit_kind == passage.retrieval_unit_kind)
        )
        for passage_id in selected_ids
        if (passage := passage_by_id.get(passage_id)) is not None
    ]
    if not selectors:
        return {}

    rows = (
        await session.execute(
            select(Passage, DocumentVersion, Document)
            .join(DocumentVersion, DocumentVersion.id == Passage.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                Document.workspace_id == workspace_id,
                DocumentVersion.state == "active",
                Document.active_version_id == DocumentVersion.id,
                or_(*selectors),
            )
            .order_by(
                Document.display_name,
                DocumentVersion.version_number,
                Passage.sequence_number,
                Passage.id,
            )
        )
    ).all()
    grouped: dict[tuple[UUID | None, str], list[EquivalentSource]] = defaultdict(list)
    for passage, version, document in rows:
        grouped[(passage.embedding_cache_id, passage.retrieval_unit_kind)].append(
            EquivalentSource(
                passage_id=passage.id,
                document_id=document.id,
                document_version_id=version.id,
                document_name=document.display_name,
                locator=passage.locator,
            )
        )
    return {
        passage_id: grouped.get(
            (passage.embedding_cache_id, passage.retrieval_unit_kind), []
        )
        for passage_id in selected_ids
        if (passage := passage_by_id.get(passage_id)) is not None
    }


async def selected_passage_metadata(
    session: AsyncSession,
    selected_ids: list[UUID],
    passage_by_id: dict[UUID, Passage],
    root_ids_by_evidence: dict[UUID, list[UUID]],
    equivalent_sources: dict[UUID, list[EquivalentSource]],
    *,
    retrieval_strategy: str,
) -> list[dict[str, object]]:
    if not selected_ids:
        return []
    version_ids = {
        passage_by_id[passage_id].document_version_id for passage_id in selected_ids
    }
    versions = {
        version.id: version
        for version in await session.scalars(
            select(DocumentVersion).where(DocumentVersion.id.in_(version_ids))
        )
    }
    return [
        {
            "passage_id": str(passage_id),
            "document_version_id": str(passage.document_version_id),
            "embedding_cache_id": (
                str(passage.embedding_cache_id)
                if passage.embedding_cache_id is not None
                else None
            ),
            "chunking_profile": versions[passage.document_version_id].chunking_profile,
            "structural_metadata": passage.structural_metadata,
            "source_kind": _source_kind(passage.locator),
            "retrieval_strategy": retrieval_strategy,
            "retrieval_root_ids": [
                str(root_id) for root_id in root_ids_by_evidence[passage_id]
            ],
            "equivalent_sources": [
                source.model_dump(mode="json")
                for source in equivalent_sources.get(passage_id, [])
            ],
        }
        for passage_id in selected_ids
        for passage in [passage_by_id[passage_id]]
    ]


def _source_kind(locator: dict[str, object]) -> str:
    kind = locator.get("kind")
    if kind == "slack_message" or (
        kind == "message_range" and locator.get("source") == "slack"
    ):
        return "slack"
    if kind == "teams_message" or (
        kind == "message_range" and locator.get("source") == "teams"
    ):
        return "teams"
    if kind == "pdf_page":
        return "pdf"
    if kind == "docx_paragraphs":
        return "docx"
    return "text"
