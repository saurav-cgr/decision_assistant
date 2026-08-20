from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.history_service import QuestionHistoryService
from decision_assistant.answering.schemas import (
    QuestionAnswerResponse,
    QuestionHistoryListResponse,
    QuestionRequest,
)
from decision_assistant.answering.service import AnswerService
from decision_assistant.config import get_settings
from decision_assistant.db import get_session
from decision_assistant.ingestion.profiles import resolve_corpus_profile
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
        strategy=settings.retrieval_unit_strategy,
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
        chunking_profile=resolve_corpus_profile(
            settings.chunking_profile_preset,
            settings.retrieval_unit_strategy,
        ),
    )
    return AnswerService(
        session=session,
        retrieval_service=retrieval_service,
        generation_provider=providers.generation,
    )


def get_question_history_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QuestionHistoryService:
    return QuestionHistoryService(session)


@router.post("/questions", response_model=QuestionAnswerResponse)
async def answer_question(
    payload: QuestionRequest,
    request: Request,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    answer_service: Annotated[AnswerService, Depends(get_answer_service)],
    history_service: Annotated[
        QuestionHistoryService,
        Depends(get_question_history_service),
    ],
) -> QuestionAnswerResponse:
    return await history_service.answer(
        payload,
        answer_service=answer_service,
        request_id=request.state.request_id,
        workspace_id=workspace.workspace_id,
    )


@router.get("/questions/history", response_model=QuestionHistoryListResponse)
async def list_question_history(
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    history_service: Annotated[
        QuestionHistoryService,
        Depends(get_question_history_service),
    ],
    query: Annotated[str | None, Query(max_length=2_000)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> QuestionHistoryListResponse:
    return await history_service.list_history(
        workspace_id=workspace.workspace_id,
        query=query,
        page=page,
        page_size=page_size,
    )


@router.get("/questions/history/{history_id}", response_model=QuestionAnswerResponse)
async def get_question_history_item(
    history_id: UUID,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    history_service: Annotated[
        QuestionHistoryService,
        Depends(get_question_history_service),
    ],
) -> QuestionAnswerResponse:
    return await history_service.get_history_item(
        history_id,
        workspace_id=workspace.workspace_id,
    )
