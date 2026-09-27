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
from decision_assistant.documents.errors import (
    DisclosureNotAcknowledged,
    DocumentApiError,
)
from decision_assistant.documents.queries import (
    get_document_detail,
    list_document_items,
)
from decision_assistant.documents.schemas import (
    DocumentDetail,
    DocumentListResponse,
    FileError,
    RetryResponse,
    UploadBatchResponse,
    UploadFileResult,
)
from decision_assistant.documents.storage import (
    LocalFileStorage,
    ObjectStorage,
    StoredObjectTooLarge,
)
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    IngestionJob,
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
        # T049 (FR-014): the upload path is the gate the disclosure exists for. Enforced here, on the
        # session the route already uses, so the rule holds for every caller of `submit_uploads`
        # rather than only for callers that remember to depend on a route-level guard.
        if workspace.disclosure_acknowledged_at is None:
            raise DisclosureNotAcknowledged()
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

            duplicate = await self._session.execute(
                select(Document, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                .where(
                    Document.workspace_id == workspace.id,
                    DocumentVersion.checksum == stored.checksum,
                    DocumentVersion.state == "active",
                    Document.active_version_id == DocumentVersion.id,
                )
                .limit(1)
            )
            duplicate_match = duplicate.first()
            if duplicate_match is not None:
                duplicate_document, duplicate_version = duplicate_match
                self._storage.delete(stored.key)
                job = IngestionJob(
                    id=job_id,
                    document_id=duplicate_document.id,
                    document_version_id=duplicate_version.id,
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
                        document_id=duplicate_document.id,
                        job_id=job.id,
                        duplicate_of_document_id=duplicate_document.id,
                        duplicate_of_version_id=duplicate_version.id,
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
        return await list_document_items(self._session, workspace_id=workspace_id)

    async def get_document(
        self,
        document_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> DocumentDetail:
        return await get_document_detail(
            self._session, document_id, workspace_id=workspace_id
        )

    async def retry(
        self,
        document_id: UUID,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> RetrySubmission:
        # DB31: lock the document row for the rest of this transaction. Two
        # retries that arrive at the same time would otherwise both read the
        # same latest `failed` job (the first one's new `pending` job is not
        # visible to the other transaction yet) and both dispatch — V94's
        # double-dispatch reached through concurrency instead of a stale view.
        # The loser blocks here until the winner commits, then re-reads the
        # latest job below and is rejected with 409.
        document = await self._session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if document is None or (
            workspace_id is not None and document.workspace_id != workspace_id
        ):
            raise DocumentApiError("document_not_found", "Document not found", 404)
        # V94: must check the LATEST job overall, not merely the latest
        # `failed` one — a document can have a failed job followed by a
        # newer pending/running job (e.g. from an earlier retry already in
        # flight), and retrying against the older failed job would dispatch
        # a second concurrent ingestion for the same DocumentVersion.
        failed_job = await self._session.scalar(
            select(IngestionJob)
            .where(IngestionJob.document_id == document.id)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .limit(1)
        )
        if (
            failed_job is None
            or failed_job.status != "failed"
            or failed_job.document_version_id is None
        ):
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
