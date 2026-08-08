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
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaGenerationProvider,
)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def get_runtime_settings(request: Request) -> Settings:
    return request.app.state.settings


class LocalIngestionDispatcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def dispatch(
        self,
        *,
        document_id: UUID,
        job_id: UUID,
        source_path: Path,
        request_id: str,
    ) -> None:
        generation_provider = OllamaGenerationProvider(
            base_url=self._settings.ollama_base_url,
            model=self._settings.ollama_generation_model,
            retry_count=self._settings.model_retry_count,
            timeout_seconds=self._settings.model_timeout_seconds,
        )
        embedding_provider = OllamaEmbeddingProvider(
            base_url=self._settings.ollama_base_url,
            model=self._settings.ollama_embedding_model,
            dimension=self._settings.ollama_embedding_dimension,
            retry_count=self._settings.model_retry_count,
            timeout_seconds=self._settings.model_timeout_seconds,
        )
        async with session_factory() as session:
            service = IngestionService(
                session=session,
                embedding_provider=embedding_provider,
                decision_extractor=DecisionExtractor(generation_provider),
                metadata_extractor=MetadataExtractor(generation_provider),
                upload_directory=self._settings.upload_directory,
            )
            try:
                await service.ingest(
                    document_id,
                    source_path,
                    request_id=request_id,
                    job_id=job_id,
                )
            except Exception:
                await session.commit()
                return
            await session.commit()


def get_document_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentService:
    settings = get_runtime_settings(request)
    dispatcher: IngestionDispatcher = LocalIngestionDispatcher(settings)
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
    service: Annotated[DocumentService, Depends(get_document_service)],
    files: Annotated[list[UploadFile], File()],
) -> UploadBatchResponse:
    request_id = request.state.request_id
    submission = await service.submit_uploads(files, request_id=request_id)
    for dispatch in submission.dispatches:
        background_tasks.add_task(service.dispatch, dispatch)
    return submission.response


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentListResponse:
    return await service.list_documents()


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentDetail:
    return await service.get_document(document_id)


@router.post(
    "/{document_id}/retry",
    response_model=RetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_document(
    document_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> RetryResponse:
    submission = await service.retry(
        document_id,
        request_id=request.state.request_id,
    )
    background_tasks.add_task(service.dispatch, submission.dispatch)
    return submission.response
