from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.errors import ApplicationError
from decision_assistant.models import Document, DocumentVersion, Passage, Workspace
from decision_assistant.providers.base import EmbeddingProfile


class CorpusResetRequired(ApplicationError):
    """A stored corpus contract no longer matches the configured contract.

    There is intentionally no in-place migration path: the application never
    mixes incompatible corpus representations. Reset the database and reingest
    all source documents with the current code version.
    """

    def __init__(self) -> None:
        super().__init__(
            code="corpus_reset_required",
            message=(
                "Corpus contract changed; reset the database and reingest all "
                "source documents with the current code version"
            ),
            status_code=409,
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class CorpusState:
    configured_embedding_profile: dict[str, str | int]
    configured_chunking_profile: dict[str, object]
    active_passage_count: int
    corpus_reset_required: bool


def workspace_advisory_lock_key(workspace_id: UUID) -> int:
    return int.from_bytes(workspace_id.bytes[:8], byteorder="big", signed=True)


async def acquire_workspace_embedding_lock(
    session: AsyncSession,
    workspace_id: UUID,
) -> None:
    await session.execute(
        select(func.pg_advisory_xact_lock(workspace_advisory_lock_key(workspace_id)))
    )


async def get_corpus_state(
    session: AsyncSession,
    workspace_id: UUID,
    configured_embedding: EmbeddingProfile,
    configured_chunking: dict[str, object],
) -> CorpusState:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")

    profile = configured_embedding.as_dict()
    active = _active_passage_predicates(workspace_id)
    active_count = int(
        await session.scalar(select(func.count(Passage.id)).where(*active)) or 0
    )

    mismatched_embedding = 0
    mismatched_chunking = 0
    if active_count:
        mismatched_embedding = int(
            await session.scalar(
                select(func.count(Passage.id)).where(
                    *active,
                    Passage.embedding_profile != profile,
                )
            )
            or 0
        )
        mismatched_chunking = int(
            await session.scalar(
                select(func.count(DocumentVersion.id))
                .join(
                    Document,
                    Document.id == DocumentVersion.document_id,
                )
                .where(
                    Document.workspace_id == workspace_id,
                    DocumentVersion.state == "active",
                    Document.active_version_id == DocumentVersion.id,
                    DocumentVersion.chunking_profile != configured_chunking,
                )
            )
            or 0
        )

    return CorpusState(
        configured_embedding_profile=profile,
        configured_chunking_profile=configured_chunking,
        active_passage_count=active_count,
        corpus_reset_required=active_count > 0
        and (
            workspace.embedding_profile != profile
            or mismatched_embedding > 0
            or mismatched_chunking > 0
        ),
    )


async def require_current_corpus_profiles(
    session: AsyncSession,
    configured_embedding: EmbeddingProfile,
    configured_chunking: dict[str, object],
    workspace_id: UUID | None = None,
) -> None:
    if workspace_id is not None:
        workspace_ids = [workspace_id]
    else:
        workspace_ids = list(await session.scalars(select(Workspace.id)))
    for workspace_id in workspace_ids:
        state = await get_corpus_state(
            session,
            workspace_id,
            configured_embedding,
            configured_chunking,
        )
        if state.corpus_reset_required:
            raise CorpusResetRequired()


def _active_passage_predicates(workspace_id: UUID) -> tuple[object, ...]:
    return (
        Passage.document_version_id == DocumentVersion.id,
        DocumentVersion.document_id == Document.id,
        Document.workspace_id == workspace_id,
        DocumentVersion.state == "active",
        Document.active_version_id == DocumentVersion.id,
    )
