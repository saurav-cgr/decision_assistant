from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.errors import ApplicationError
from decision_assistant.models import (
    EMBEDDING_DIMENSION,
    Document,
    DocumentVersion,
    Passage,
    Workspace,
)
from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingProvider,
    EmbeddingPurpose,
    ProviderConfigurationInvalid,
    ProviderResponseInvalid,
)


class EmbeddingReindexRequired(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="embedding_reindex_required",
            message="Embedding reindex is required before vector retrieval",
            status_code=409,
            retryable=False,
        )


class EmbeddingSnapshotChanged(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="embedding_migration_snapshot_changed",
            message="Active document snapshot changed during embedding migration",
            status_code=409,
            retryable=True,
        )


@dataclass(frozen=True, slots=True)
class EmbeddingCorpusState:
    configured_profile: dict[str, str | int]
    corpus_active_profile: dict[str, object] | None
    active_passage_count: int
    migration_pending: bool


@dataclass(frozen=True, slots=True)
class EmbeddingMigrationResult:
    workspace_id: UUID
    passage_count: int
    embedding_profile: dict[str, str | int]


@dataclass(frozen=True, slots=True)
class _PassageSnapshot:
    passage_id: UUID
    document_version_id: UUID
    content_hash: str
    content: str

    @property
    def identity(self) -> tuple[UUID, UUID, str]:
        return self.passage_id, self.document_version_id, self.content_hash


@dataclass(frozen=True, slots=True)
class _CorpusSnapshot:
    versions: tuple[tuple[UUID, UUID], ...]
    passages: tuple[_PassageSnapshot, ...]

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.versions,
            tuple(passage.identity for passage in self.passages),
        )


def workspace_advisory_lock_key(workspace_id: UUID) -> int:
    return int.from_bytes(workspace_id.bytes[:8], byteorder="big", signed=True)


async def acquire_workspace_embedding_lock(
    session: AsyncSession,
    workspace_id: UUID,
) -> None:
    await session.execute(
        select(func.pg_advisory_xact_lock(workspace_advisory_lock_key(workspace_id)))
    )


async def get_embedding_corpus_state(
    session: AsyncSession,
    workspace_id: UUID,
    configured_profile: EmbeddingProfile,
) -> EmbeddingCorpusState:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")

    profile = configured_profile.as_dict()
    active = _active_passage_predicates(workspace_id)
    active_count = int(
        await session.scalar(select(func.count(Passage.id)).where(*active)) or 0
    )
    mismatched_count = 0
    if active_count:
        mismatched_count = int(
            await session.scalar(
                select(func.count(Passage.id)).where(
                    *active,
                    or_(
                        Passage.embedding_profile.is_(None),
                        Passage.embedding_profile != profile,
                    ),
                )
            )
            or 0
        )
    return EmbeddingCorpusState(
        configured_profile=profile,
        corpus_active_profile=workspace.embedding_profile,
        active_passage_count=active_count,
        migration_pending=active_count > 0
        and (
            workspace.embedding_profile != profile
            or mismatched_count > 0
        ),
    )


async def require_current_embedding_profile(
    session: AsyncSession,
    configured_profile: EmbeddingProfile,
    workspace_id: UUID | None = None,
) -> None:
    if workspace_id is not None:
        workspace_ids = [workspace_id]
    else:
        workspace_ids = list(await session.scalars(select(Workspace.id)))
    for workspace_id in workspace_ids:
        state = await get_embedding_corpus_state(
            session,
            workspace_id,
            configured_profile,
        )
        if state.migration_pending:
            raise EmbeddingReindexRequired()


class EmbeddingMigrationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        batch_size: int = 32,
    ) -> None:
        if batch_size < 1:
            raise ValueError("Embedding migration batch size must be positive")
        self._session = session
        self._embedding_provider = embedding_provider
        self._batch_size = batch_size

    async def run(self, workspace_id: UUID) -> EmbeddingMigrationResult:
        if self._embedding_provider.profile.dimension != EMBEDDING_DIMENSION:
            raise ProviderConfigurationInvalid()
        transaction = (
            self._session.begin_nested()
            if self._session.in_transaction()
            else self._session.begin()
        )
        async with transaction:
            workspace = await self._session.get(Workspace, workspace_id)
            if workspace is None:
                raise ValueError("Workspace not found")
            await acquire_workspace_embedding_lock(self._session, workspace_id)
            snapshot = await self._snapshot(workspace_id)
            staged_vectors = await self._embed(snapshot.passages)
            current = await self._snapshot(workspace_id)
            if current.identity != snapshot.identity:
                raise EmbeddingSnapshotChanged()

            profile = self._embedding_provider.profile.as_dict()
            passage_by_id = {
                passage.id: passage
                for passage in await self._session.scalars(
                    select(Passage).where(
                        Passage.id.in_(
                            [item.passage_id for item in snapshot.passages]
                        )
                    )
                )
            }
            for item, vector in zip(snapshot.passages, staged_vectors, strict=True):
                passage = passage_by_id[item.passage_id]
                passage.embedding = vector
                passage.embedding_profile = profile
            workspace.embedding_profile = profile
            await self._session.flush()

        return EmbeddingMigrationResult(
            workspace_id=workspace_id,
            passage_count=len(snapshot.passages),
            embedding_profile=profile,
        )

    async def _snapshot(self, workspace_id: UUID) -> _CorpusSnapshot:
        version_rows = (
            await self._session.execute(
                select(Document.id, DocumentVersion.id)
                .join(
                    DocumentVersion,
                    DocumentVersion.id == Document.active_version_id,
                )
                .where(
                    Document.workspace_id == workspace_id,
                    DocumentVersion.state == "active",
                )
                .order_by(Document.id)
            )
        ).all()
        passage_rows = (
            await self._session.execute(
                select(
                    Passage.id,
                    Passage.document_version_id,
                    Passage.content_hash,
                    Passage.content,
                )
                .join(
                    DocumentVersion,
                    DocumentVersion.id == Passage.document_version_id,
                )
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    Document.workspace_id == workspace_id,
                    DocumentVersion.state == "active",
                    Document.active_version_id == DocumentVersion.id,
                )
                .order_by(Document.id, Passage.sequence_number, Passage.id)
            )
        ).all()
        return _CorpusSnapshot(
            versions=tuple((document_id, version_id) for document_id, version_id in version_rows),
            passages=tuple(
                _PassageSnapshot(
                    passage_id=passage_id,
                    document_version_id=version_id,
                    content_hash=content_hash,
                    content=content,
                )
                for passage_id, version_id, content_hash, content in passage_rows
            ),
        )

    async def _embed(
        self,
        passages: tuple[_PassageSnapshot, ...],
    ) -> list[list[float]]:
        staged: list[list[float]] = []
        expected_dimension = self._embedding_provider.profile.dimension
        for start in range(0, len(passages), self._batch_size):
            batch = passages[start : start + self._batch_size]
            vectors = await self._embedding_provider.embed(
                [passage.content for passage in batch],
                purpose=EmbeddingPurpose.DOCUMENT,
            )
            if len(vectors) != len(batch):
                raise ProviderResponseInvalid()
            for vector in vectors:
                if len(vector) != expected_dimension or not all(
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and isfinite(value)
                    for value in vector
                ):
                    raise ProviderResponseInvalid()
                staged.append([float(value) for value in vector])
        return staged


def _active_passage_predicates(workspace_id: UUID) -> tuple[object, ...]:
    return (
        Passage.document_version_id == DocumentVersion.id,
        DocumentVersion.document_id == Document.id,
        Document.workspace_id == workspace_id,
        DocumentVersion.state == "active",
        Document.active_version_id == DocumentVersion.id,
    )
