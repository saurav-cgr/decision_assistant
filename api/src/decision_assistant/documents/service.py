import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.documents.schemas import (
    ActiveVersionDetail,
    DocumentDetail,
    DocumentListItem,
    DocumentListResponse,
    FileError,
    PassageDetail,
    RetryResponse,
    UploadBatchResponse,
    UploadFileResult,
)
from decision_assistant.documents.storage import (
    LocalFileStorage,
    ObjectStorage,
    StoredObjectTooLarge,
)
from decision_assistant.errors import ApplicationError
from decision_assistant.models import (
    Decision,
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
)
from decision_assistant.workspace.service import WorkspaceService

SUPPORTED_MEDIA_TYPES = {
    ".md": frozenset({"text/markdown", "text/plain"}),
    ".txt": frozenset({"text/plain"}),
    ".pdf": frozenset({"application/pdf"}),
    ".docx": frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
}

class IngestionDispatcher(Protocol):
    async def dispatch(
        self,
        *,
        document_id: UUID,
        job_id: UUID,
        source_path: Path,
        request_id: str,
    ) -> None: ...


class DocumentApiError(ApplicationError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    document_id: UUID
    job_id: UUID
    source_path: Path
    request_id: str


@dataclass(frozen=True, slots=True)
class UploadSubmission:
    response: UploadBatchResponse
    dispatches: list[DispatchRequest]


@dataclass(frozen=True, slots=True)
class RetrySubmission:
    response: RetryResponse
    dispatch: DispatchRequest


class DocumentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        dispatcher: IngestionDispatcher,
        storage: ObjectStorage | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._dispatcher = dispatcher
        self._storage = storage or LocalFileStorage(settings.upload_directory)

    async def submit_uploads(
        self,
        uploads: list[UploadFile],
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> UploadSubmission:
        if workspace_id is None:
            workspace = await WorkspaceService(
                self._session
            ).get_or_create_active()
        else:
            workspace = await WorkspaceService(self._session).get(workspace_id)
        results: list[UploadFileResult] = []
        dispatches: list[DispatchRequest] = []

        for upload in uploads:
            filename = _sanitize_filename(upload.filename or "upload")
            error = _validate_file(filename, upload.content_type)
            if error is not None:
                await upload.close()
                results.append(
                    UploadFileResult(
                        filename=filename,
                        status="rejected",
                        error=error,
                    )
                )
                continue

            existing = await self._session.scalar(
                select(Document).where(
                    Document.workspace_id == workspace.id,
                    Document.display_name == filename,
                )
            )
            document_id = existing.id if existing is not None else uuid4()
            version_id = uuid4()
            job_id = uuid4()
            object_key = (
                f"documents/{document_id}/incoming/"
                f"{version_id}-{filename}"
            )
            try:
                stored = await self._storage.put_upload(
                    key=object_key,
                    upload=upload,
                    max_bytes=self._settings.max_upload_bytes,
                )
            except StoredObjectTooLarge:
                results.append(
                    UploadFileResult(
                        filename=filename,
                        status="rejected",
                        error=FileError(
                            code="file_too_large",
                            message="File exceeds configured upload limit",
                        ),
                    )
                )
                continue

            document = existing or Document(
                id=document_id,
                workspace_id=workspace.id,
                display_name=filename,
                media_type=upload.content_type or "application/octet-stream",
            )
            if existing is None:
                self._session.add(document)

            active_version = (
                await self._session.get(DocumentVersion, document.active_version_id)
                if document.active_version_id is not None
                else None
            )
            if active_version is not None and active_version.checksum == stored.checksum:
                self._storage.delete(stored.key)
                job = IngestionJob(
                    id=job_id,
                    document_id=document.id,
                    document_version_id=active_version.id,
                    stage="unchanged",
                    status="completed",
                    progress=100,
                    attempt_count=1,
                    request_id=request_id,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                )
                self._session.add(job)
                await self._session.flush()
                results.append(
                    UploadFileResult(
                        filename=filename,
                        status="accepted",
                        document_id=document.id,
                        job_id=job.id,
                    )
                )
                continue

            version_number = (
                await self._session.scalar(
                    select(func.coalesce(func.max(DocumentVersion.version_number), 0)).where(
                        DocumentVersion.document_id == document.id
                    )
                )
            ) + 1
            version = DocumentVersion(
                id=version_id,
                document_id=document.id,
                version_number=version_number,
                checksum=stored.checksum,
                storage_path=stored.key,
                state="staging",
            )
            job = IngestionJob(
                id=job_id,
                document_id=document.id,
                document_version_id=version.id,
                stage="queued",
                status="pending",
                progress=0,
                attempt_count=0,
                request_id=request_id,
            )
            self._session.add_all([version, job])
            await self._session.flush()
            dispatches.append(
                DispatchRequest(
                    document_id=document.id,
                    job_id=job.id,
                    source_path=stored.local_path,
                    request_id=request_id,
                )
            )
            results.append(
                UploadFileResult(
                    filename=filename,
                    status="accepted",
                    document_id=document.id,
                    job_id=job.id,
                )
            )

        return UploadSubmission(
            response=UploadBatchResponse(request_id=request_id, results=results),
            dispatches=dispatches,
        )

    async def dispatch(self, request: DispatchRequest) -> None:
        await self._dispatcher.dispatch(
            document_id=request.document_id,
            job_id=request.job_id,
            source_path=request.source_path,
            request_id=request.request_id,
        )

    async def list_documents(self, *, workspace_id: UUID | None = None) -> DocumentListResponse:
        statement = select(Document).order_by(Document.created_at.desc())
        if workspace_id is not None:
            statement = statement.where(Document.workspace_id == workspace_id)
        documents = list(await self._session.scalars(statement))
        items: list[DocumentListItem] = []
        for document in documents:
            job = await self._session.scalar(
                select(IngestionJob)
                .where(IngestionJob.document_id == document.id)
                .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
                .limit(1)
            )
            version = (
                await self._session.get(DocumentVersion, document.active_version_id)
                if document.active_version_id is not None
                else None
            )
            decision_count = (
                await self._session.scalar(
                    select(func.count())
                    .select_from(Decision)
                    .where(
                        Decision.document_version_id == version.id,
                        Decision.retired.is_(False),
                    )
                )
                if version is not None
                else 0
            )
            modification_state = None
            if job is not None and job.stage == "unchanged":
                modification_state = "unchanged"
            elif version is not None:
                modification_state = "modified" if version.version_number > 1 else "new"
            items.append(
                DocumentListItem(
                    id=document.id,
                    display_name=document.display_name,
                    media_type=document.media_type,
                    active_version_id=document.active_version_id,
                    status=job.status if job is not None else None,
                    stage=job.stage if job is not None else None,
                    progress=job.progress if job is not None else None,
                    error=job.error if job is not None else None,
                    title=version.title if version is not None else None,
                    document_date=version.document_date if version is not None else None,
                    participants=version.participants if version is not None else [],
                    source_type=version.source_type if version is not None else None,
                    project=version.project if version is not None else None,
                    modification_state=modification_state,
                    decision_count=decision_count or 0,
                )
            )
        return DocumentListResponse(items=items)

    async def get_document(
        self,
        document_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> DocumentDetail:
        document = await self._session.get(Document, document_id)
        if document is None or (
            workspace_id is not None and document.workspace_id != workspace_id
        ):
            raise DocumentApiError("document_not_found", "Document not found", 404)

        version = (
            await self._session.get(DocumentVersion, document.active_version_id)
            if document.active_version_id is not None
            else None
        )
        passages = (
            list(
                await self._session.scalars(
                    select(Passage)
                    .where(Passage.document_version_id == version.id)
                    .order_by(Passage.sequence_number)
                )
            )
            if version is not None
            else []
        )
        return DocumentDetail(
            id=document.id,
            display_name=document.display_name,
            media_type=document.media_type,
            active_version=(
                ActiveVersionDetail(
                    id=version.id,
                    version_number=version.version_number,
                    title=version.title,
                    document_date=version.document_date,
                    participants=version.participants,
                    source_type=version.source_type,
                    project=version.project,
                    state=version.state,
                )
                if version is not None
                else None
            ),
            passages=[
                PassageDetail(
                    sequence_number=passage.sequence_number,
                    content=passage.content,
                    locator=passage.locator,
                    structural_metadata=passage.structural_metadata,
                )
                for passage in passages
            ],
        )

    async def retry(
        self,
        document_id: UUID,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> RetrySubmission:
        document = await self._session.get(Document, document_id)
        if document is None or (
            workspace_id is not None and document.workspace_id != workspace_id
        ):
            raise DocumentApiError("document_not_found", "Document not found", 404)
        failed_job = await self._session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.document_id == document.id,
                IngestionJob.status == "failed",
            )
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .limit(1)
        )
        if failed_job is None or failed_job.document_version_id is None:
            raise DocumentApiError("retry_not_available", "No failed ingestion to retry", 409)
        version = await self._session.get(
            DocumentVersion,
            failed_job.document_version_id,
        )
        if version is None:
            raise DocumentApiError("retry_not_available", "Failed version not found", 409)

        version.state = "staging"
        version.error = None
        job = IngestionJob(
            document_id=document.id,
            document_version_id=version.id,
            stage="queued",
            status="pending",
            progress=0,
            attempt_count=failed_job.attempt_count + 1,
            request_id=request_id,
        )
        self._session.add(job)
        await self._session.flush()
        dispatch = DispatchRequest(
            document_id=document.id,
            job_id=job.id,
            source_path=self._storage.local_path(version.storage_path),
            request_id=request_id,
        )
        return RetrySubmission(
            response=RetryResponse(
                request_id=request_id,
                document_id=document.id,
                job_id=job.id,
            ),
            dispatch=dispatch,
        )


def _sanitize_filename(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name.replace("\x00", "")
    sanitized = re.sub(r"[^A-Za-z0-9._ -]", "_", basename).strip(" .")
    return sanitized or "upload"


def _validate_file(filename: str, media_type: str | None) -> FileError | None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_MEDIA_TYPES:
        return FileError(
            code="unsupported_file_type",
            message="Supported file types are .md, .txt, .pdf, and .docx",
        )
    if media_type not in SUPPORTED_MEDIA_TYPES[suffix]:
        return FileError(
            code="unsupported_media_type",
            message="Declared media type does not match file extension",
        )
    return None
