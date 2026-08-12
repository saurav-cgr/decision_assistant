from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.db import get_session
from decision_assistant.workspace.schemas import (
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceListResponse,
    WorkspaceRename,
    WorkspaceSummary,
)
from decision_assistant.workspace.service import WorkspaceService

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def get_workspace_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkspaceService:
    return WorkspaceService(session)


async def _summarize(
    service: WorkspaceService,
    workspace,
) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        status=workspace.status,
        is_active=workspace.is_active,
        document_count=await service.document_count(workspace.id),
        created_at=workspace.created_at,
    )


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceListResponse:
    workspaces = await service.list()
    items = [await _summarize(service, w) for w in workspaces]
    return WorkspaceListResponse(items=items)


@router.post("", response_model=WorkspaceDetail, status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.create(name=payload.name)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
    )


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
async def get_workspace(
    workspace_id: UUID,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.get(workspace_id)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceDetail)
async def rename_workspace(
    workspace_id: UUID,
    payload: WorkspaceRename,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.rename(workspace_id, payload.name)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
    )


@router.post("/{workspace_id}/activate", response_model=WorkspaceDetail)
async def activate_workspace(
    workspace_id: UUID,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.activate(workspace_id)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
    )


@router.post("/{workspace_id}/archive", response_model=WorkspaceDetail)
async def archive_workspace(
    workspace_id: UUID,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.archive(workspace_id)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
    )


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> None:
    await service.delete_archived(workspace_id)


def _summary_fields(summary: WorkspaceSummary) -> dict:
    return summary.model_dump()
