from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.schemas import QuestionRequest, QuestionResponse
from decision_assistant.answering.service import AnswerService
from decision_assistant.db import get_session
from decision_assistant.providers.factory import (
    ProviderBundleFactory,
    get_provider_bundle_factory,
)
from decision_assistant.retrieval.service import HybridRetrievalService

router = APIRouter(prefix="/api/v1", tags=["questions"])


def get_answer_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_factory: Annotated[
        ProviderBundleFactory,
        Depends(get_provider_bundle_factory),
    ],
) -> AnswerService:
    providers = provider_factory()
    retrieval_service = HybridRetrievalService(
        session=session,
        embedding_provider=providers.embedding,
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
    service: Annotated[AnswerService, Depends(get_answer_service)],
) -> QuestionResponse:
    return await service.answer(payload, request_id=request.state.request_id)
