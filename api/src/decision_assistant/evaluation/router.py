from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.evaluation.schemas import (
    EvaluationRunRequest,
    EvaluationRunResponse,
)
from decision_assistant.evaluation.service import (
    EvaluationService,
    GenerationClaimJudge,
    RuntimeEvaluationExecutor,
)
from decision_assistant.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaGenerationProvider,
)

router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])


def get_evaluation_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EvaluationService:
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
    return EvaluationService(
        session=session,
        dataset_path=settings.evaluation_dataset_path,
        executor=RuntimeEvaluationExecutor(
            session=session,
            embedding_provider=embedding_provider,
            generation_provider=generation_provider,
        ),
        judge=GenerationClaimJudge(generation_provider),
    )


@router.post(
    "/runs",
    response_model=EvaluationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    payload: EvaluationRunRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> EvaluationRunResponse:
    run = await service.create_run(payload)
    response = await service.get_run(run.id)
    background_tasks.add_task(service.execute_run, run.id)
    return response


@router.get("/runs/{run_id}", response_model=EvaluationRunResponse)
async def get_run(
    run_id: UUID,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> EvaluationRunResponse:
    return await service.get_run(run_id)
