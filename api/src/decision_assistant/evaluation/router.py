from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.db import get_session, session_factory
from decision_assistant.ingestion.profiles import resolve_corpus_profile
from decision_assistant.evaluation.schemas import (
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationRunSummaryResponse,
)
from decision_assistant.evaluation.service import (
    EvaluationService,
    GenerationClaimJudge,
    RuntimeEvaluationExecutor,
)
from decision_assistant.providers.factory import (
    ProviderBundleFactory,
    get_provider_bundle_factory,
)
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/evaluations", tags=["evaluations"]
)


def _build_evaluation_service(
    session: AsyncSession,
    settings: Settings,
    providers: Any,
) -> EvaluationService:
    return EvaluationService(
        session=session,
        dataset_path=settings.evaluation_dataset_path,
        executor=RuntimeEvaluationExecutor(
            session=session,
            embedding_provider=providers.embedding,
            generation_provider=providers.generation,
            chunking_profile=resolve_corpus_profile(
                settings.chunking_profile_preset,
                settings.retrieval_unit_strategy,
            ),
            retrieval_unit_strategy=settings.retrieval_unit_strategy,
        ),
        judge=GenerationClaimJudge(providers.generation),
    )


class EvaluationBackgroundRunner:
    def __init__(
        self,
        settings: Settings,
        provider_factory: ProviderBundleFactory,
        *,
        session_maker: Any = session_factory,
    ) -> None:
        self._settings = settings
        self._provider_factory = provider_factory
        self._session_maker = session_maker

    async def dispatch(self, run_id: UUID) -> None:
        async with self._session_maker() as session:
            service = _build_evaluation_service(
                session,
                self._settings,
                self._provider_factory(),
            )
            try:
                await service.execute_run(run_id)
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()


def get_evaluation_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_factory: Annotated[
        ProviderBundleFactory,
        Depends(get_provider_bundle_factory),
    ],
) -> EvaluationService:
    settings: Settings = request.app.state.settings
    providers = provider_factory()
    return _build_evaluation_service(session, settings, providers)


def get_evaluation_background_runner(
    request: Request,
    provider_factory: Annotated[
        ProviderBundleFactory,
        Depends(get_provider_bundle_factory),
    ],
) -> EvaluationBackgroundRunner:
    return EvaluationBackgroundRunner(
        request.app.state.settings,
        provider_factory,
    )


@router.get("/runs", response_model=list[EvaluationRunSummaryResponse])
async def list_runs(
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
    limit: int = 10,
) -> list[EvaluationRunSummaryResponse]:
    return await service.list_runs(
        workspace_id=workspace.workspace_id, limit=limit
    )


@router.post(
    "/runs",
    response_model=EvaluationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    payload: EvaluationRunRequest,
    background_tasks: BackgroundTasks,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
    runner: Annotated[
        EvaluationBackgroundRunner,
        Depends(get_evaluation_background_runner),
    ],
) -> EvaluationRunResponse:
    run = await service.create_run(
        payload, workspace_id=workspace.workspace_id
    )
    response = await service.get_run(
        run.id, workspace_id=workspace.workspace_id
    )
    background_tasks.add_task(runner.dispatch, run.id)
    return response


@router.get("/runs/{run_id}", response_model=EvaluationRunResponse)
async def get_run(
    run_id: UUID,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> EvaluationRunResponse:
    return await service.get_run(run_id, workspace_id=workspace.workspace_id)
