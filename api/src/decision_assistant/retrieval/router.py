from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.db import get_session
from decision_assistant.providers.factory import (
    ProviderBundleFactory,
    get_provider_bundle_factory,
)
from decision_assistant.retrieval.schemas import (
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    RetrievalTraceResponse,
)
from decision_assistant.retrieval.service import HybridRetrievalService

router = APIRouter(prefix="/api/v1", tags=["retrieval"])


def get_retrieval_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_factory: Annotated[
        ProviderBundleFactory,
        Depends(get_provider_bundle_factory),
    ],
) -> HybridRetrievalService:
    providers = provider_factory()
    return HybridRetrievalService(
        session=session,
        embedding_provider=providers.embedding,
    )


@router.post("/retrieval/search", response_model=RetrievalSearchResponse)
async def search(
    payload: RetrievalSearchRequest,
    request: Request,
    service: Annotated[HybridRetrievalService, Depends(get_retrieval_service)],
) -> RetrievalSearchResponse:
    return await service.search(payload, request_id=request.state.request_id)


@router.get(
    "/retrieval-traces/{trace_id}",
    response_model=RetrievalTraceResponse,
)
async def get_trace(
    trace_id: UUID,
    service: Annotated[HybridRetrievalService, Depends(get_retrieval_service)],
) -> RetrievalTraceResponse:
    return await service.get_trace(trace_id)
