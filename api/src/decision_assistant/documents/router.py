from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.db import get_session, session_factory
from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.documents.schemas import (
    DocumentDetail,
    DocumentListResponse,
    RetryResponse,
    UploadBatchResponse,
)
from decision_assistant.documents.service import DocumentService, IngestionDispatcher
from decision_assistant.errors import ApplicationError
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.profiles import resolve_corpus_profile
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.models import DocumentVersion, IngestionJob
from decision_assistant.providers.factory import (
    ProviderBundleFactory,
    get_provider_bundle_factory,
)
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/documents", tags=["documents"]
)


def get_runtime_settings(request: Request) -> Settings:
    return request.app.state.settings


class LocalIngestionDispatcher:
    def __init__(
        self,
        settings: Settings,
        provider_factory: ProviderBundleFactory,
    ) -> None:
        self._settings = settings
        self._provider_factory = provider_factory

    async def dispatch(
        self,
        *,
        document_id: UUID,
        job_id: UUID,
        source_path: Path,
        request_id: str,
    ) -> None:
        async with session_factory() as session:
            try:
                providers = self._provider_factory()
                service = IngestionService(
                    session=session,
                    embedding_provider=providers.embedding,
                    decision_extractor=DecisionExtractor(
                        providers.generation,
                        max_prompt_characters=self._settings.gemini_max_prompt_characters,
                    ),
                    metadata_extractor=MetadataExtractor(providers.generation),
                    upload_directory=self._settings.upload_directory,
                    chunking_profile=resolve_corpus_profile(
                        self._settings.chunking_profile_preset,
                        self._settings.retrieval_unit_strategy,
                    ),
                    retrieval_unit_strategy=self._settings.retrieval_unit_strategy,
                )
                await service.ingest(
                    document_id,
                    source_path,
                    request_id=request_id,
                    job_id=job_id,
                )
            except Exception as exc:
                await _record_dispatch_failure(session, job_id, exc)
                await session.commit()
                return
            await session.commit()


async def _record_dispatch_failure(
    session: AsyncSession,
    job_id: UUID,
    error: Exception,
) -> None:
    job = await session.get(IngestionJob, job_id)
    if job is None:
        return
    if isinstance(error, ApplicationError):
        payload = {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
            "details": None,
        }
    else:
        payload = {
            "code": "ingestion_failed",
            "message": "Document ingestion failed",
            "retryable": False,
            "details": None,
        }
    job.stage = "failed"
    job.status = "failed"
    job.error = payload
    job.finished_at = datetime.now(timezone.utc)
    if job.document_version_id is not None:
        version = await session.get(DocumentVersion, job.document_version_id)
        if version is not None and version.state in {"staging", "failed"}:
            version.state = "failed"
            version.error = payload
    await session.flush()


def get_document_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_factory: Annotated[
        ProviderBundleFactory,
        Depends(get_provider_bundle_factory),
    ],
) -> DocumentService:
    settings = get_runtime_settings(request)
    dispatcher: IngestionDispatcher = LocalIngestionDispatcher(
        settings,
        provider_factory,
    )
    return DocumentService(
        session=session,
        settings=settings,
        dispatcher=dispatcher,
    )


@router.post(
    "/upload",
    response_model=UploadBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    files: Annotated[list[UploadFile], File()],
) -> UploadBatchResponse:
    request_id = request.state.request_id
    submission = await service.submit_uploads(
        files,
        request_id=request_id,
        workspace_id=workspace.workspace_id,
    )
    for dispatch in submission.dispatches:
        background_tasks.add_task(service.dispatch, dispatch)
    return submission.response


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentListResponse:
    return await service.list_documents(workspace_id=workspace.workspace_id)


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: UUID,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentDetail:
    return await service.get_document(
        document_id, workspace_id=workspace.workspace_id
    )


@router.post(
    "/{document_id}/retry",
    response_model=RetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_document(
    document_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> RetryResponse:
    submission = await service.retry(
        document_id,
        request_id=request.state.request_id,
        workspace_id=workspace.workspace_id,
    )
    background_tasks.add_task(service.dispatch, submission.dispatch)
    return submission.response
