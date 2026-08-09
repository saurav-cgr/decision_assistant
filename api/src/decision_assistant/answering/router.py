from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.schemas import QuestionRequest, QuestionResponse
from decision_assistant.answering.service import AnswerService
from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaGenerationProvider,
)
from decision_assistant.retrieval.service import HybridRetrievalService

router = APIRouter(prefix="/api/v1", tags=["questions"])


def get_answer_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnswerService:
    settings: Settings = request.app.state.settings
    embedding_provider = OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
        dimension=settings.ollama_embedding_dimension,
        retry_count=settings.model_retry_count,
        timeout_seconds=settings.model_timeout_seconds,
    )
    generation_provider = OllamaGenerationProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_generation_model,
        retry_count=settings.model_retry_count,
        timeout_seconds=settings.model_timeout_seconds,
    )
    retrieval_service = HybridRetrievalService(
        session=session,
        embedding_provider=embedding_provider,
    )
    return AnswerService(
        session=session,
        retrieval_service=retrieval_service,
        generation_provider=generation_provider,
    )


@router.post("/questions", response_model=QuestionResponse)
async def answer_question(
    payload: QuestionRequest,
    request: Request,
    service: Annotated[AnswerService, Depends(get_answer_service)],
) -> QuestionResponse:
    return await service.answer(payload, request_id=request.state.request_id)
