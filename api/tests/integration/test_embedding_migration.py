from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from decision_assistant.commands import reindex_embeddings as reindex_command
from decision_assistant.config import get_settings
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    DecisionRelation,
    DecisionRevision,
    Document,
    DocumentVersion,
    Passage,
    Workspace,
)
from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingPurpose,
    ProviderConfigurationInvalid,
    ProviderResponseInvalid,
    ProviderUnavailable,
)
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.providers.fakes import FakeGenerationProvider
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.workspace.embedding_migration import (
    EmbeddingMigrationService,
    EmbeddingReindexRequired,
    EmbeddingSnapshotChanged,
    get_embedding_corpus_state,
    require_current_embedding_profile,
    workspace_advisory_lock_key,
)


async def seed_active_passages(
    session: AsyncSession,
    *,
    profile: EmbeddingProfile,
    count: int = 2,
) -> tuple[Workspace, Document, DocumentVersion, list[Passage]]:
    workspace = Workspace(
        name=f"Embedding migration {uuid4()}",
        embedding_profile=profile.as_dict(),
    )
    session.add(workspace)
    await session.flush()
    document = Document(
        workspace_id=workspace.id,
        display_name="migration.md",
        media_type="text/markdown",
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        title="Migration",
        participants=[],
        checksum=sha256(b"migration").hexdigest(),
        storage_path="fixtures/migration.md",
        normalized_content="migration",
        state="active",
    )
    session.add(version)
    await session.flush()
    document.active_version_id = version.id
    provider = FakeEmbeddingProvider(dimension=768)
    vectors = await provider.embed(
        [f"passage {index}" for index in range(count)],
        purpose=EmbeddingPurpose.DOCUMENT,
    )
    passages = []
    for index, vector in enumerate(vectors):
        content = f"passage {index}"
        passage = Passage(
            document_version_id=version.id,
            sequence_number=index,
            content=content,
            start_offset=index * 20,
            end_offset=(index * 20) + len(content),
            content_hash=sha256(content.encode()).hexdigest(),
            locator={"kind": "lines", "start": index + 1, "end": index + 1},
            embedding=vector,
            embedding_profile=profile.as_dict(),
        )
        session.add(passage)
        passages.append(passage)
    await session.flush()
    return workspace, document, version, passages


@pytest.mark.asyncio
async def test_embedding_state_distinguishes_configured_active_and_pending(
    db_session: AsyncSession,
) -> None:
    configured = FakeEmbeddingProvider(dimension=768).profile
    old = replace(configured, provider="legacy", model="old-model")
    workspace = Workspace(
        name=f"Empty migration {uuid4()}",
        embedding_profile=old.as_dict(),
    )
    db_session.add(workspace)
    await db_session.flush()

    empty_state = await get_embedding_corpus_state(
        db_session, workspace.id, configured
    )
    assert empty_state.configured_profile == configured.as_dict()
    assert empty_state.corpus_active_profile == old.as_dict()
    assert empty_state.active_passage_count == 0
    assert empty_state.migration_pending is False

    workspace, _, _, passages = await seed_active_passages(
        db_session,
        profile=old,
    )
    state = await get_embedding_corpus_state(db_session, workspace.id, configured)
    assert state.configured_profile == configured.as_dict()
    assert state.corpus_active_profile == old.as_dict()
    assert state.active_passage_count == len(passages)
    assert state.migration_pending is True


@pytest.mark.asyncio
async def test_retrieval_gate_rejects_missing_or_different_active_profiles(
    db_session: AsyncSession,
) -> None:
    provider = FakeEmbeddingProvider(dimension=768)
    workspace, _, _, passages = await seed_active_passages(
        db_session,
        profile=provider.profile,
    )
    await require_current_embedding_profile(db_session, provider.profile)

    passages[0].embedding_profile = None
    await db_session.flush()
    with pytest.raises(EmbeddingReindexRequired) as error:
        await require_current_embedding_profile(db_session, provider.profile)
    assert error.value.code == "embedding_reindex_required"
    assert error.value.details is None

    passages[0].embedding_profile = provider.profile.as_dict()
    workspace.embedding_profile = replace(
        provider.profile,
        adapter_config_version="legacy-v0",
    ).as_dict()
    await db_session.flush()
    with pytest.raises(EmbeddingReindexRequired):
        await require_current_embedding_profile(db_session, provider.profile)


class FailingSecondBatchProvider(FakeEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__(dimension=768)
        self.calls = 0

    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        self.calls += 1
        if self.calls == 2:
            raise ProviderUnavailable()
        return await super().embed(texts, purpose=purpose)


class ChangedSpaceProvider(FakeEmbeddingProvider):
    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        vectors = await super().embed(texts, purpose=purpose)
        return [[-value for value in vector] for vector in vectors]


class LockCheckingProvider(ChangedSpaceProvider):
    def __init__(self, *, engine: AsyncEngine, workspace_id: object) -> None:
        super().__init__(dimension=768)
        self._engine = engine
        self._workspace_id = workspace_id
        self.lock_was_held = False

    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        async with self._engine.begin() as connection:
            acquired = await connection.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        workspace_advisory_lock_key(self._workspace_id)  # type: ignore[arg-type]
                    )
                )
            )
        self.lock_was_held = acquired is False
        return await super().embed(texts, purpose=purpose)


class DriftingProvider(ChangedSpaceProvider):
    def __init__(self, *, session: AsyncSession, document_id: object) -> None:
        super().__init__(dimension=768)
        self._session = session
        self._document_id = document_id
        self._drifted = False

    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        if not self._drifted:
            await self._session.execute(
                update(Document)
                .where(Document.id == self._document_id)
                .values(active_version_id=None)
            )
            self._drifted = True
        return await super().embed(texts, purpose=purpose)


class BooleanVectorProvider(FakeEmbeddingProvider):
    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        self.purposes.append(purpose)
        return [[True] * self.profile.dimension for _ in texts]


@pytest.mark.asyncio
async def test_failed_batch_leaves_all_vectors_and_profiles_unchanged(
    db_session: AsyncSession,
) -> None:
    old = replace(FakeEmbeddingProvider(dimension=768).profile, provider="legacy")
    workspace, _, _, passages = await seed_active_passages(
        db_session,
        profile=old,
        count=2,
    )
    old_rows = {
        passage.id: (list(passage.embedding), dict(passage.embedding_profile or {}))
        for passage in passages
    }
    workspace_id = workspace.id

    with pytest.raises(ProviderUnavailable):
        await EmbeddingMigrationService(
            session=db_session,
            embedding_provider=FailingSecondBatchProvider(),
            batch_size=1,
        ).run(workspace_id)

    refreshed = list(
        await db_session.scalars(
            select(Passage)
            .join(DocumentVersion, DocumentVersion.id == Passage.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.workspace_id == workspace_id)
        )
    )
    active_workspace = await db_session.get(Workspace, workspace_id)
    assert active_workspace is not None
    assert active_workspace.embedding_profile == old.as_dict()
    assert {
        passage.id: (list(passage.embedding), dict(passage.embedding_profile or {}))
        for passage in refreshed
    } == old_rows


@pytest.mark.asyncio
async def test_migration_rejects_non_schema_dimension_before_provider_call(
    db_session: AsyncSession,
) -> None:
    old = replace(FakeEmbeddingProvider(dimension=768).profile, provider="legacy")
    workspace, _, _, _ = await seed_active_passages(db_session, profile=old)
    invalid_provider = FakeEmbeddingProvider(dimension=8)

    with pytest.raises(ProviderConfigurationInvalid):
        await EmbeddingMigrationService(
            session=db_session,
            embedding_provider=invalid_provider,
        ).run(workspace.id)

    assert invalid_provider.purposes == []


@pytest.mark.asyncio
async def test_migration_rejects_boolean_vector_values(
    db_session: AsyncSession,
) -> None:
    old = replace(FakeEmbeddingProvider(dimension=768).profile, provider="legacy")
    workspace, _, _, passages = await seed_active_passages(db_session, profile=old)
    before = {passage.id: list(passage.embedding) for passage in passages}

    with pytest.raises(ProviderResponseInvalid):
        await EmbeddingMigrationService(
            session=db_session,
            embedding_provider=BooleanVectorProvider(dimension=768),
        ).run(workspace.id)

    refreshed = list(
        await db_session.scalars(
            select(Passage).where(Passage.id.in_(list(before)))
        )
    )
    assert {passage.id: list(passage.embedding) for passage in refreshed} == before


@pytest.mark.asyncio
async def test_successful_migration_changes_only_vectors_and_profiles(
    db_session: AsyncSession,
) -> None:
    target = ChangedSpaceProvider(dimension=768)
    old = replace(target.profile, provider="legacy", model="legacy-model")
    workspace, _, version, passages = await seed_active_passages(
        db_session,
        profile=old,
        count=3,
    )
    extracted = Decision(
        document_version_id=version.id,
        statement="Initial decision",
        status="active",
        provenance="extracted",
        review_state="supported",
        user_edited=False,
        retired=False,
    )
    corrected = Decision(
        document_version_id=version.id,
        statement="User-corrected decision",
        status="superseded",
        provenance="user_corrected",
        review_state="supported",
        user_edited=True,
        retired=False,
    )
    db_session.add_all([extracted, corrected])
    await db_session.flush()
    evidence = DecisionEvidence(
        decision_id=corrected.id,
        passage_id=passages[0].id,
        field_name="statement",
        start_offset=passages[0].start_offset,
        end_offset=passages[0].end_offset,
        support_state="supported",
        is_primary=True,
        content_hash=passages[0].content_hash,
    )
    relation = DecisionRelation(
        source_decision_id=corrected.id,
        target_decision_id=extracted.id,
        relation_type="supersedes",
        authority="user_confirmed",
        confidence="high",
        rationale="Manual correction",
    )
    revision = DecisionRevision(
        decision_id=corrected.id,
        field_name="statement",
        old_value="Initial decision",
        new_value="User-corrected decision",
        evidence_passage_ids=[passages[0].id],
        support_state="supported",
    )
    db_session.add_all([evidence, relation, revision])
    await db_session.flush()
    derived_before = {
        "decisions": [
            (
                item.id,
                item.statement,
                item.status,
                item.provenance,
                item.review_state,
                item.user_edited,
                item.retired,
            )
            for item in (extracted, corrected)
        ],
        "evidence": (
            evidence.id,
            evidence.decision_id,
            evidence.passage_id,
            evidence.start_offset,
            evidence.end_offset,
            evidence.content_hash,
        ),
        "relation": (
            relation.id,
            relation.source_decision_id,
            relation.target_decision_id,
            relation.relation_type,
            relation.authority,
        ),
        "revision": (
            revision.id,
            revision.decision_id,
            revision.field_name,
            revision.old_value,
            revision.new_value,
            tuple(revision.evidence_passage_ids),
            revision.support_state,
        ),
    }
    immutable_before = [
        (
            passage.id,
            passage.document_version_id,
            passage.sequence_number,
            passage.content,
            passage.start_offset,
            passage.end_offset,
            passage.content_hash,
            dict(passage.locator),
        )
        for passage in passages
    ]
    old_vectors = {passage.id: list(passage.embedding) for passage in passages}
    workspace_id = workspace.id
    version_id = version.id

    result = await EmbeddingMigrationService(
        session=db_session,
        embedding_provider=target,
        batch_size=2,
    ).run(workspace_id)

    migrated = list(
        await db_session.scalars(
            select(Passage)
            .where(Passage.document_version_id == version_id)
            .order_by(Passage.sequence_number)
        )
    )
    active_workspace = await db_session.get(Workspace, workspace_id)
    assert result.passage_count == 3
    assert target.purposes == [EmbeddingPurpose.DOCUMENT, EmbeddingPurpose.DOCUMENT]
    assert active_workspace is not None
    assert active_workspace.embedding_profile == target.profile.as_dict()
    assert all(passage.embedding_profile == target.profile.as_dict() for passage in migrated)
    assert all(list(passage.embedding) != old_vectors[passage.id] for passage in migrated)
    assert [
        (
            passage.id,
            passage.document_version_id,
            passage.sequence_number,
            passage.content,
            passage.start_offset,
            passage.end_offset,
            passage.content_hash,
            dict(passage.locator),
        )
        for passage in migrated
    ] == immutable_before
    assert await db_session.scalar(
        select(func.count(DocumentVersion.id)).where(DocumentVersion.id == version_id)
    ) == 1
    migrated_decisions = list(
        await db_session.scalars(
            select(Decision)
            .where(Decision.document_version_id == version_id)
            .order_by(Decision.statement)
        )
    )
    migrated_evidence = await db_session.get(DecisionEvidence, evidence.id)
    migrated_relation = await db_session.get(DecisionRelation, relation.id)
    migrated_revision = await db_session.get(DecisionRevision, revision.id)
    assert migrated_evidence is not None
    assert migrated_relation is not None
    assert migrated_revision is not None
    assert {
        "decisions": [
            (
                item.id,
                item.statement,
                item.status,
                item.provenance,
                item.review_state,
                item.user_edited,
                item.retired,
            )
            for item in migrated_decisions
        ],
        "evidence": (
            migrated_evidence.id,
            migrated_evidence.decision_id,
            migrated_evidence.passage_id,
            migrated_evidence.start_offset,
            migrated_evidence.end_offset,
            migrated_evidence.content_hash,
        ),
        "relation": (
            migrated_relation.id,
            migrated_relation.source_decision_id,
            migrated_relation.target_decision_id,
            migrated_relation.relation_type,
            migrated_relation.authority,
        ),
        "revision": (
            migrated_revision.id,
            migrated_revision.decision_id,
            migrated_revision.field_name,
            migrated_revision.old_value,
            migrated_revision.new_value,
            tuple(migrated_revision.evidence_passage_ids),
            migrated_revision.support_state,
        ),
    } == derived_before


@pytest.mark.asyncio
async def test_workspace_lock_is_held_during_provider_calls(
    db_session: AsyncSession,
) -> None:
    old = replace(FakeEmbeddingProvider(dimension=768).profile, provider="legacy")
    workspace, _, _, _ = await seed_active_passages(db_session, profile=old)
    engine = db_session.bind
    assert isinstance(engine, AsyncEngine)
    provider = LockCheckingProvider(engine=engine, workspace_id=workspace.id)

    await EmbeddingMigrationService(
        session=db_session,
        embedding_provider=provider,
    ).run(workspace.id)

    assert provider.lock_was_held is True


@pytest.mark.asyncio
async def test_snapshot_drift_rolls_back_membership_vectors_and_profiles(
    db_session: AsyncSession,
) -> None:
    old = replace(FakeEmbeddingProvider(dimension=768).profile, provider="legacy")
    workspace, document, version, passages = await seed_active_passages(
        db_session,
        profile=old,
    )
    before = {
        passage.id: (list(passage.embedding), dict(passage.embedding_profile or {}))
        for passage in passages
    }

    with pytest.raises(EmbeddingSnapshotChanged) as error:
        await EmbeddingMigrationService(
            session=db_session,
            embedding_provider=DriftingProvider(
                session=db_session,
                document_id=document.id,
            ),
        ).run(workspace.id)

    assert error.value.code == "embedding_migration_snapshot_changed"
    await db_session.refresh(document)
    await db_session.refresh(workspace)
    refreshed = list(
        await db_session.scalars(
            select(Passage).where(Passage.document_version_id == version.id)
        )
    )
    assert document.active_version_id == version.id
    assert workspace.embedding_profile == old.as_dict()
    assert {
        passage.id: (list(passage.embedding), dict(passage.embedding_profile or {}))
        for passage in refreshed
    } == before


@pytest.mark.asyncio
async def test_default_workspace_command_commits_cutover_for_fresh_sessions(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ChangedSpaceProvider(dimension=768)
    old = replace(target.profile, provider="legacy", model="legacy-model")
    workspace, _, version, passages = await seed_active_passages(
        db_session,
        profile=old,
    )
    workspace.created_at = datetime(1900, 1, 1, tzinfo=timezone.utc)
    workspace_id = workspace.id
    passage_ids = [passage.id for passage in passages]
    await db_session.commit()
    bundle = ProviderBundle(
        embedding=target,
        generation=FakeGenerationProvider(),
    )
    monkeypatch.setattr(
        reindex_command,
        "create_embedding_provider_handle",
        lambda settings: bundle,
    )

    try:
        result = await reindex_command.reindex_embeddings(
            settings=get_settings(),
            workspace_id=None,
            batch_size=1,
        )

        sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
        async with sessions() as fresh_session:
            persisted_workspace = await fresh_session.get(Workspace, workspace_id)
            persisted_passages = list(
                await fresh_session.scalars(
                    select(Passage)
                    .where(Passage.id.in_(passage_ids))
                    .order_by(Passage.sequence_number)
                )
            )
        assert result["workspace_id"] == str(workspace_id)
        assert persisted_workspace is not None
        assert persisted_workspace.embedding_profile == target.profile.as_dict()
        assert all(
            passage.embedding_profile == target.profile.as_dict()
            for passage in persisted_passages
        )
        assert target.purposes == [
            EmbeddingPurpose.DOCUMENT,
            EmbeddingPurpose.DOCUMENT,
        ]
    finally:
        await db_session.execute(
            delete(Workspace).where(Workspace.id == workspace_id)
        )
        await db_session.commit()
