from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceCreate(WorkspaceBase):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceRename(WorkspaceBase):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceSummary(WorkspaceBase):
    id: UUID
    name: str
    status: str
    is_active: bool
    document_count: int
    created_at: datetime


class WorkspaceListResponse(WorkspaceBase):
    items: list[WorkspaceSummary]


class WorkspaceDetail(WorkspaceSummary):
    embedding_profile: dict[str, Any] | None
