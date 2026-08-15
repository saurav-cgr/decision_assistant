from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.schemas import QuestionRequest, QuestionResponse
from decision_assistant.answering.service import AnswerService
from decision_assistant.config import get_settings
from decision_assistant.db import get_session
from decision_assistant.providers.factory import (
    ProviderBundleFactory,
    get_provider_bundle_factory,
)
from decision_assistant.retrieval.reranking import GenerationReranker
from decision_assistant.retrieval.service import (
    HybridRetrievalService,
    RetrievalConfig,
)
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["questions"])


def get_answer_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_factory: Annotated[
        ProviderBundleFactory,
        Depends(get_provider_bundle_factory),
    ],
) -> AnswerService:
    providers = provider_factory()
    settings = get_settings()
    config = RetrievalConfig(
        rerank_enabled=settings.rerank_enabled,
        rerank_candidate_limit=settings.rerank_candidate_limit,
        rerank_min_candidates=settings.rerank_min_candidates,
        rerank_final_limit=settings.rerank_final_limit,
    )
    reranker = (
        GenerationReranker(providers.generation)
        if settings.rerank_enabled
        else None
    )
    retrieval_service = HybridRetrievalService(
        session=session,
        embedding_provider=providers.embedding,
        config=config,
        reranker=reranker,
    )
    return AnswerService(
        session=session,
        retrieval_service=retrieval_service,
        generation_provider=providers.generation,
    )


@router.post("/questions", response_model=QuestionResponse)
async def answer_question(
    payload: QuestionRequest,
    request: Request,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[AnswerService, Depends(get_answer_service)],
) -> QuestionResponse:
    return await service.answer(
        payload,
        request_id=request.state.request_id,
        workspace_id=workspace.workspace_id,
    )
