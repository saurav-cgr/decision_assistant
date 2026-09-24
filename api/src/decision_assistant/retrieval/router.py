from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import get_settings
from decision_assistant.db import get_session
from decision_assistant.ingestion.profiles import resolve_corpus_profile
from decision_assistant.providers.factory import (
    ProviderBundleFactory,
    get_provider_bundle_factory,
)
from decision_assistant.retrieval.reranking import GenerationReranker
from decision_assistant.retrieval.schemas import (
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    RetrievalTraceResponse,
)
from decision_assistant.retrieval.service import (
    HybridRetrievalService,
    RetrievalConfig,
)
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["retrieval"])


def get_retrieval_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_factory: Annotated[
        ProviderBundleFactory,
        Depends(get_provider_bundle_factory),
    ],
) -> HybridRetrievalService:
    providers = provider_factory()
    settings = get_settings()
    config = RetrievalConfig(
        rerank_enabled=settings.rerank_enabled,
        rerank_candidate_limit=settings.rerank_candidate_limit,
        rerank_min_candidates=settings.rerank_min_candidates,
        rerank_final_limit=settings.rerank_final_limit,
        strategy=settings.retrieval_unit_strategy,
    )
    reranker = (
        GenerationReranker(providers.generation)
        if settings.rerank_enabled
        else None
    )
    return HybridRetrievalService(
        session=session,
        embedding_provider=providers.embedding,
        config=config,
        reranker=reranker,
        chunking_profile=resolve_corpus_profile(
            settings.chunking_profile_preset,
            settings.retrieval_unit_strategy,
        ),
    )


@router.post("/retrieval/search", response_model=RetrievalSearchResponse)
async def search(
    payload: RetrievalSearchRequest,
    request: Request,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[HybridRetrievalService, Depends(get_retrieval_service)],
) -> RetrievalSearchResponse:
    return await service.search(
        payload,
        request_id=request.state.request_id,
        workspace_id=workspace.workspace_id,
    )


@router.get(
    "/retrieval-traces/{trace_id}",
    response_model=RetrievalTraceResponse,
)
async def get_trace(
    trace_id: UUID,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[HybridRetrievalService, Depends(get_retrieval_service)],
) -> RetrievalTraceResponse:
    return await service.get_trace(
        trace_id, workspace_id=workspace.workspace_id
    )
