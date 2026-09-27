"""Decision-evidence retrieval and the trace API (DB53).

Split out of `test_hybrid_retrieval.py` (corpus/passage retrieval) so both files stay under
AGENTS.md's 500-line cap; the shared scaffolding lives in `tests/support/retrieval_fixtures.py`.
"""

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.main import create_app
from decision_assistant.providers.base import EmbeddingPurpose
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.retrieval.repository import RetrievalRepository
from decision_assistant.retrieval.router import get_retrieval_service
from decision_assistant.retrieval.schemas import RetrievalFilters, RetrievalSearchRequest
from decision_assistant.retrieval.service import HybridRetrievalService
from decision_assistant.workspace.context import WorkspaceContext, get_workspace_context
from tests.support.retrieval_fixtures import (
    create_passage,
    create_version,
    create_workspace,
)

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
        workspace_id=workspace.id,
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
        workspace_id=workspace.id,
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
async def test_decision_search_keeps_the_highest_rank_for_shared_passage(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session)
    _, version = await create_version(db_session, workspace, name="decision-rank.md")
    passage = await create_passage(
        db_session,
        version,
        sequence_number=0,
        content="The rollout dependency remains unresolved.",
        embedding=[0.0] * 768,
    )
    decisions = [
        Decision(
            workspace_id=workspace.id,
            document_version_id=version.id,
            statement="authentication rollout needs more operational review",
            status="active",
            reasons=[],
            alternatives=[],
            project="Atlas",
            topic="authentication",
            provenance="extracted",
            review_state="supported",
            user_edited=False,
            retired=False,
        ),
        Decision(
            workspace_id=workspace.id,
            document_version_id=version.id,
            statement="authentication",
            status="active",
            reasons=[],
            alternatives=[],
            project="Atlas",
            topic="authentication",
            provenance="extracted",
            review_state="supported",
            user_edited=False,
            retired=False,
        ),
    ]
    db_session.add_all(decisions)
    await db_session.flush()
    db_session.add_all(
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
        for decision in decisions
    )
    await db_session.flush()

    results = await RetrievalRepository(db_session).decision_search(
        "authentication",
        RetrievalFilters(),
        limit=1,
        workspace_id=workspace.id,
    )

    assert results[0].passage.id == passage.id
    assert results[0].raw_score > 0.1


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
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=workspace.id)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        search_response = await client.post(
            f"/api/v1/workspaces/{workspace.id}/retrieval/search",
            json={"question": "authentication", "filters": {}},
            headers={"x-request-id": "trace-request"},
        )
        assert search_response.status_code == 200
        trace_id = search_response.json()["trace_id"]

        trace_response = await client.get(
            f"/api/v1/workspaces/{workspace.id}/retrieval-traces/{trace_id}"
        )
        missing_response = await client.get(
            f"/api/v1/workspaces/{workspace.id}/retrieval-traces/{uuid4()}"
        )

    assert trace_response.status_code == 200
    assert trace_response.json()["id"] == trace_id
    assert trace_response.json()["request_id"] == "trace-request"
    assert missing_response.status_code == 404
    assert missing_response.json()["code"] == "not_found"
    assert UUID(missing_response.json()["request_id"])
