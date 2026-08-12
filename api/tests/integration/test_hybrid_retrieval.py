from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.main import create_app
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    Document,
    DocumentVersion,
    Passage,
    RetrievalTrace,
    Workspace,
)
from decision_assistant.providers.base import EmbeddingPurpose
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.retrieval.router import get_retrieval_service
from decision_assistant.retrieval.repository import RetrievalRepository
from decision_assistant.retrieval.schemas import RetrievalFilters, RetrievalSearchRequest
from decision_assistant.retrieval.service import HybridRetrievalService
from decision_assistant.workspace.embedding_migration import EmbeddingReindexRequired

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
    )
    session.add(passage)
    await session.flush()
    return passage


@pytest.mark.asyncio
async def test_hybrid_retrieval_abstains_before_provider_call_when_reindex_required(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    workspace = await create_workspace(db_session)
    _, version = await create_version(db_session, workspace, name="legacy.md")
    passage = await create_passage(
        db_session,
        version,
        sequence_number=0,
        content="Legacy authentication decision.",
        embedding=[0.0] * 768,
    )
    passage.embedding_profile = None
    await db_session.flush()

    with pytest.raises(EmbeddingReindexRequired) as error:
        await HybridRetrievalService(
            session=db_session,
            embedding_provider=embedding_provider,
        ).search(
            RetrievalSearchRequest(question="authentication"),
            request_id="retrieval-needs-migration",
        )

    assert error.value.code == "embedding_reindex_required"
    assert embedding_provider.purposes == []


@pytest.mark.asyncio
async def test_vector_query_filters_active_versions_by_configured_passage_profile(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session)
    _, active_version = await create_version(
        db_session,
        workspace,
        name="profile-filter.md",
    )
    matching = await create_passage(
        db_session,
        active_version,
        sequence_number=0,
        content="Matching profile.",
        embedding=[1.0] + ([0.0] * 767),
    )
    mismatched = await create_passage(
        db_session,
        active_version,
        sequence_number=1,
        content="Mismatched profile.",
        embedding=[1.0] + ([0.0] * 767),
    )
    mismatched.embedding_profile = {
        **EMBEDDING_PROFILE,
        "adapter_config_version": "legacy-v0",
    }
    _, retired_version = await create_version(
        db_session,
        workspace,
        name="retired-profile.md",
        state="retired",
    )
    retired = await create_passage(
        db_session,
        retired_version,
        sequence_number=0,
        content="Retired profile.",
        embedding=[1.0] + ([0.0] * 767),
    )
    await db_session.flush()

    results = await RetrievalRepository(db_session).semantic_search(
        [1.0] + ([0.0] * 767),
        RetrievalFilters(),
        embedding_profile=EMBEDDING_PROFILE,
        limit=10,
    )

    assert [result.passage.id for result in results] == [matching.id]
    assert mismatched.id not in {result.passage.id for result in results}
    assert retired.id not in {result.passage.id for result in results}


@pytest.mark.asyncio
async def test_hybrid_retrieval_caps_sources_and_excludes_retired_versions(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    query_vector = (
        await embedding_provider.embed(
            ["authentication"], purpose=EmbeddingPurpose.DOCUMENT
        )
    )[0]
    workspace = await create_workspace(db_session)
    _, active_version = await create_version(
        db_session,
        workspace,
        name="active.md",
        participants=["Maya"],
    )
    _, retired_version = await create_version(
        db_session,
        workspace,
        name="retired.md",
        state="retired",
        participants=["Maya"],
    )
    active_passages = [
        await create_passage(
            db_session,
            active_version,
            sequence_number=index,
            content=f"Authentication decision evidence number {index}.",
            embedding=query_vector,
        )
        for index in range(22)
    ]
    retired = await create_passage(
        db_session,
        retired_version,
        sequence_number=0,
        content="Authentication evidence from a retired version.",
        embedding=query_vector,
    )
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
    )

    result = await service.search(
        RetrievalSearchRequest(question="authentication"),
        request_id="retrieval-1",
    )
    trace = await db_session.get(RetrievalTrace, result.trace_id)

    assert trace is not None
    assert len(trace.semantic_candidates) == 20
    assert len(trace.keyword_candidates) == 20
    assert retired.id not in {item.passage_id for item in result.results}
    assert str(retired.id) not in {
        candidate["passage_id"]
        for candidates in (
            trace.semantic_candidates,
            trace.keyword_candidates,
            trace.decision_candidates,
        )
        for candidate in candidates
    }
    active_ids = {str(passage.id) for passage in active_passages}
    assert set(trace.selected_passage_ids) <= active_ids
    assert len(trace.selected_passage_ids) == 5
    assert set(trace.timings) >= {
        "semantic_ms",
        "keyword_ms",
        "decision_ms",
        "fusion_ms",
        "total_ms",
    }
    assert trace.configuration == {
        "semantic_limit": 20,
        "keyword_limit": 20,
        "decision_limit": 20,
        "rrf_k": 60,
        "top_k": 5,
    }


@pytest.mark.asyncio
async def test_explicit_metadata_filters_apply_before_ranking(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    query_vector = (
        await embedding_provider.embed(
            ["authentication"], purpose=EmbeddingPurpose.DOCUMENT
        )
    )[0]
    workspace = await create_workspace(db_session)
    variants = [
        ("match.md", "text/markdown", "Atlas", date(2026, 7, 15), ["Maya"]),
        ("wrong-project.md", "text/markdown", "Beta", date(2026, 7, 15), ["Maya"]),
        ("wrong-date.md", "text/markdown", "Atlas", date(2025, 7, 15), ["Maya"]),
        ("wrong-type.txt", "text/plain", "Atlas", date(2026, 7, 15), ["Maya"]),
        ("wrong-person.md", "text/markdown", "Atlas", date(2026, 7, 15), ["Ravi"]),
    ]
    passages: dict[str, Passage] = {}
    for name, media_type, project, document_date, participants in variants:
        _, version = await create_version(
            db_session,
            workspace,
            name=name,
            media_type=media_type,
            project=project,
            document_date=document_date,
            participants=participants,
        )
        passages[name] = await create_passage(
            db_session,
            version,
            sequence_number=0,
            content="Authentication was postponed.",
            embedding=query_vector,
        )
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
    )

    result = await service.search(
        RetrievalSearchRequest(
            question="authentication",
            filters=RetrievalFilters(
                person="Maya",
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 31),
                project="Atlas",
                document_type="text/markdown",
            ),
        ),
        request_id="retrieval-filtered",
    )

    assert [item.passage_id for item in result.results] == [passages["match.md"].id]
    trace = await db_session.get(RetrievalTrace, result.trace_id)
    assert trace is not None
    assert trace.filters == {
        "person": "Maya",
        "date_from": "2026-07-01",
        "date_to": "2026-07-31",
        "project": "Atlas",
        "document_type": "text/markdown",
    }


@pytest.mark.asyncio
async def test_decision_fields_add_their_evidence_passage_as_candidate(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    workspace = await create_workspace(db_session)
    _, version = await create_version(db_session, workspace, name="decision.md")
    passage = await create_passage(
        db_session,
        version,
        sequence_number=0,
        content="The rollout dependency remains unresolved.",
        embedding=(
            await embedding_provider.embed(
                ["unrelated storage note"], purpose=EmbeddingPurpose.DOCUMENT
            )
        )[0],
    )
    decision = Decision(
        document_version_id=version.id,
        statement="Postpone authentication.",
        status="active",
        reasons=["Import flow is unstable."],
        alternatives=[],
        project="Atlas",
        topic="authentication",
        provenance="extracted",
        review_state="supported",
        user_edited=False,
        retired=False,
    )
    db_session.add(decision)
    await db_session.flush()
    db_session.add(
        DecisionEvidence(
            decision_id=decision.id,
            passage_id=passage.id,
            field_name=None,
            start_offset=0,
            end_offset=len(passage.content),
            support_state="supported",
            is_primary=True,
            content_hash=passage.content_hash,
        )
    )
    await db_session.flush()
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
    )

    result = await service.search(
        RetrievalSearchRequest(question="authentication"),
        request_id="retrieval-decision",
    )
    trace = await db_session.get(RetrievalTrace, result.trace_id)

    assert trace is not None
    assert trace.decision_candidates[0]["passage_id"] == str(passage.id)
    fused = next(
        item
        for item in trace.fused_results
        if item["passage_id"] == str(passage.id)
    )
    assert fused["source_ranks"]["decision"] == 1


@pytest.mark.asyncio
async def test_trace_api_returns_trace_and_stable_not_found(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    query_vector = (
        await embedding_provider.embed(
            ["authentication"], purpose=EmbeddingPurpose.DOCUMENT
        )
    )[0]
    workspace = await create_workspace(db_session)
    _, version = await create_version(db_session, workspace, name="trace.md")
    await create_passage(
        db_session,
        version,
        sequence_number=0,
        content="Authentication was postponed.",
        embedding=query_vector,
    )
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
    )
    app = create_app(Settings())

    async def override_service() -> HybridRetrievalService:
        return service

    app.dependency_overrides[get_retrieval_service] = override_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        search_response = await client.post(
            "/api/v1/retrieval/search",
            json={"question": "authentication", "filters": {}},
            headers={"x-request-id": "trace-request"},
        )
        assert search_response.status_code == 200
        trace_id = search_response.json()["trace_id"]

        trace_response = await client.get(f"/api/v1/retrieval-traces/{trace_id}")
        missing_response = await client.get(f"/api/v1/retrieval-traces/{uuid4()}")

    assert trace_response.status_code == 200
    assert trace_response.json()["id"] == trace_id
    assert trace_response.json()["request_id"] == "trace-request"
    assert missing_response.status_code == 404
    assert missing_response.json()["code"] == "not_found"
    assert UUID(missing_response.json()["request_id"])
