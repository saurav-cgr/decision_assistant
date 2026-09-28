from datetime import datetime
from typing import Any, Literal
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
    disclosure_acknowledged_at: datetime | None


class CorpusRebuildStatus(WorkspaceBase):
    status: str
    reason: str
    documents_total: int
    documents_completed: int
    started_at: datetime | None
    finished_at: datetime | None
    error: dict[str, Any] | None


class ProviderDisclosureResponse(WorkspaceBase):
    #: The generation provider (kept under the original name for back-compat with the contract).
    provider: str
    #: Which provider builds the search index and which generates answers. Named separately so a
    #: mixed configuration (e.g. local generation + remote embedding) can be disclosed accurately.
    generation_provider: str
    embedding_provider: str
    generation_sends_document_text_remotely: bool
    embedding_sends_document_text_remotely: bool
    #: True when *any* configured provider can send document text off this machine.
    sends_document_text_remotely: bool
    acknowledged_at: datetime | None


class ProviderSwitchRequest(WorkspaceBase):
    """Body of `POST /workspace/{workspace_id}/provider` (contracts/api-additions.md).

    `Literal` rather than a plain `str`: an unknown provider is a 422 from FastAPI's own validation,
    before any state is read or written.
    """

    generation_provider: Literal["gemini", "ollama"]
    embedding_provider: Literal["gemini", "ollama"]
    confirm_rebuild: bool = False


class ProviderConfigResponse(WorkspaceBase):
    generation_provider: str
    embedding_provider: str
    embedding_profile_changed: bool
    documents_total: int
    #: DB65: True when this switch made a provider start sending document text off the machine, so
    #: every workspace's disclosure acknowledgement was cleared. Uploads stay blocked until the
    #: user acknowledges again.
    disclosure_acknowledgement_cleared: bool = False
    #: Present only when this request dispatched a rebuild (202).
    rebuild: CorpusRebuildStatus | None = None
