from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileError(ApiModel):
    code: str
    message: str


class UploadFileResult(ApiModel):
    filename: str
    status: Literal["accepted", "rejected"]
    document_id: UUID | None = None
    job_id: UUID | None = None
    duplicate_of_document_id: UUID | None = None
    duplicate_of_version_id: UUID | None = None
    error: FileError | None = None


class UploadBatchResponse(ApiModel):
    request_id: str
    results: list[UploadFileResult]


class RetryResponse(ApiModel):
    request_id: str
    status: Literal["accepted"] = "accepted"
    document_id: UUID
    job_id: UUID


class DocumentListItem(ApiModel):
    id: UUID
    display_name: str
    media_type: str
    active_version_id: UUID | None
    status: str | None
    stage: str | None
    progress: int | None
    error: dict[str, Any] | None
    title: str | None
    document_date: date | None
    participants: list[str]
    source_type: str | None
    project: str | None
    modification_state: Literal["new", "unchanged", "modified"] | None
    decision_count: int


class DocumentListResponse(ApiModel):
    items: list[DocumentListItem]


class ActiveVersionDetail(ApiModel):
    id: UUID
    version_number: int
    title: str | None
    document_date: date | None
    participants: list[str]
    source_type: str | None
    project: str | None
    state: str


class PassageDetail(ApiModel):
    sequence_number: int
    content: str
    locator: dict[str, Any]
    structural_metadata: dict[str, Any]


class DocumentDetail(ApiModel):
    id: UUID
    display_name: str
    media_type: str
    active_version: ActiveVersionDetail | None
    passages: list[PassageDetail]
