import asyncio
from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.models import Document, DocumentVersion, Passage, Workspace
from decision_assistant.providers.base import EmbeddingPurpose
from decision_assistant.providers.fakes import FakeEmbeddingProvider, FakeGenerationProvider
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.retrieval.reranking import (
    GenerationReranker,
    RerankCandidate,
    resolve_reranked_order,
)
from decision_assistant.retrieval.schemas import RetrievalSearchRequest
from decision_assistant.retrieval.service import HybridRetrievalService, RetrievalConfig


def test_resolve_reranked_order_reorders_and_appends_omitted() -> None:
    a, b, c, d = (uuid4() for _ in range(4))
    result = resolve_reranked_order([b, a], [a, b, c, d])
    assert result == [b, a, c, d]


def test_resolve_drops_duplicates_and_unknown_ids() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    unknown = uuid4()
    result = resolve_reranked_order([b, a, b, unknown], [a, b, c])
    assert result == [b, a, c]


def test_resolve_empty_ranking_is_unusable() -> None:
    a, b = uuid4(), uuid4()
    assert resolve_reranked_order([], [a, b]) is None


def test_rerank_config_validates_limit_relationships() -> None:
    with pytest.raises(ValueError):
        RetrievalConfig(rerank_candidate_limit=12, rerank_final_limit=20)
    with pytest.raises(ValueError):
        RetrievalConfig(rerank_candidate_limit=12, rerank_min_candidates=13)
    with pytest.raises(ValueError):
        RetrievalConfig(rerank_candidate_limit=0)
    RetrievalConfig(rerank_enabled=True)


@pytest.mark.asyncio
async def test_reranker_sends_roles_to_user_and_system() -> None:
    a, b = uuid4(), uuid4()
    provider = FakeGenerationProvider(
        [{"passage_ids": [str(b), str(a)]}]
    )
    reranker = GenerationReranker(provider)

    result = await reranker.rerank(
        "Why was authentication postponed?",
        [RerankCandidate(a, "content a"), RerankCandidate(b, "content b")],
    )

    assert result == [b, a]
    request = provider.requests[0]
    assert "untrusted" in request.system_instruction
    assert "Why was authentication postponed?" not in request.system_instruction
    assert "Why was authentication postponed?" in request.user_content
    assert "content a" in request.user_content


async def _corpus(
    db_session: AsyncSession,
    count: int,
) -> tuple[Workspace, FakeEmbeddingProvider, list[Passage]]:
    workspace = Workspace(
        name=f"Rerank {uuid4()}",
        embedding_profile=FakeEmbeddingProvider(dimension=768).profile.as_dict(),
    )
    db_session.add(workspace)
    await db_session.flush()
    document = Document(
        workspace_id=workspace.id,
        display_name="rerank.md",
        media_type="text/markdown",
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        checksum=sha256(b"rerank").hexdigest(),
        storage_path="fixtures/rerank.md",
        normalized_content="",
        chunking_profile=CURRENT_CHUNKING_PROFILE,
        state="active",
    )
    db_session.add(version)
    await db_session.flush()
    document.active_version_id = version.id
    embedding = FakeEmbeddingProvider(dimension=768)
    vectors = await embedding.embed(
        [f"Authentication detail {index}." for index in range(count)],
        purpose=EmbeddingPurpose.DOCUMENT,
    )
    passages: list[Passage] = []
    for index in range(count):
        content = f"Authentication detail {index}."
        passage = Passage(
            document_version_id=version.id,
            sequence_number=index,
            content=content,
            start_offset=0,
            end_offset=len(content),
            content_hash=sha256(content.encode()).hexdigest(),
            locator={"kind": "lines", "start": index + 1, "end": index + 1},
            embedding=vectors[index],
            embedding_profile=embedding.profile.as_dict(),
        )
        db_session.add(passage)
        passages.append(passage)
    await db_session.flush()
    return workspace, embedding, passages


class FakeReranker:
    profile = {"provider": "fake", "model": "rerank"}

    def __init__(self, order: list[UUID] | None = None, error: Exception | None = None):
        self.order = order
        self.error = error

    async def rerank(self, question: str, candidates: list[RerankCandidate]) -> list[UUID]:
        if self.error is not None:
            raise self.error
        if self.order is not None:
            return list(self.order)
        return [candidate.passage_id for candidate in candidates]


@pytest.mark.asyncio
async def test_disabled_rerank_selects_rrf_top_five(db_session: AsyncSession) -> None:
    workspace, embedding, passages = await _corpus(db_session, 8)
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding,
        config=RetrievalConfig(rerank_enabled=False),
        reranker=FakeReranker(order=[passages[7].id]),
    )

    response = await service.search(
        RetrievalSearchRequest(question="authentication"),
        request_id="no-rerank",
        workspace_id=workspace.id,
    )

    assert len(response.results) == 5
    trace = await service.get_trace(response.trace_id, workspace_id=workspace.id)
    assert trace.rerank is None


@pytest.mark.asyncio
async def test_reranker_reorders_and_records_trace(db_session: AsyncSession) -> None:
    workspace, embedding, passages = await _corpus(db_session, 8)
    desired = [passages[7].id] + [p.id for p in passages[:4]]
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding,
        config=RetrievalConfig(rerank_enabled=True),
        reranker=FakeReranker(order=desired),
    )

    response = await service.search(
        RetrievalSearchRequest(question="authentication"),
        request_id="rerank-on",
        workspace_id=workspace.id,
    )

    assert [r.passage_id for r in response.results] == desired[:5]
    trace = await service.get_trace(response.trace_id, workspace_id=workspace.id)
    assert trace.rerank is not None
    assert trace.rerank["status"] == "completed"
    assert trace.rerank["fallback_reason"] is None
    assert trace.timings["rerank_ms"] >= 0
    assert trace.selected_passage_metadata
    assert trace.selected_passage_metadata[0]["chunking_profile"]["algorithm"] == "structural-token-v2"
    assert "structural_metadata" in trace.selected_passage_metadata[0]


@pytest.mark.asyncio
async def test_reranker_provider_error_falls_back_to_rrf(db_session: AsyncSession) -> None:
    workspace, embedding, passages = await _corpus(db_session, 8)
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding,
        config=RetrievalConfig(rerank_enabled=True),
        reranker=FakeReranker(error=RuntimeError("boom")),
    )

    response = await service.search(
        RetrievalSearchRequest(question="authentication"),
        request_id="rerank-fail",
        workspace_id=workspace.id,
    )

    assert len(response.results) == 5
    trace = await service.get_trace(response.trace_id, workspace_id=workspace.id)
    assert trace.rerank is not None
    assert trace.rerank["status"] == "provider_error"
    assert trace.rerank["fallback_reason"] == "provider_error"


@pytest.mark.asyncio
async def test_cancelled_error_is_not_swallowed(db_session: AsyncSession) -> None:
    workspace, embedding, passages = await _corpus(db_session, 8)
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding,
        config=RetrievalConfig(rerank_enabled=True),
        reranker=FakeReranker(error=asyncio.CancelledError()),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.search(
            RetrievalSearchRequest(question="authentication"),
            request_id="rerank-cancel",
            workspace_id=workspace.id,
        )
