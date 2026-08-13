from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.db import get_session
from decision_assistant.decisions.schemas import (
    DecisionCorrectionRequest,
    DecisionDetail,
    DecisionListResponse,
    DecisionRelationRequest,
    DecisionRelationResponse,
    DecisionStatus,
    SupportState,
)
from decision_assistant.decisions.service import DecisionService
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/decisions", tags=["decisions"]
)


def get_decision_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DecisionService:
    return DecisionService(session)


@router.get("", response_model=DecisionListResponse)
async def list_decisions(
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DecisionService, Depends(get_decision_service)],
    decision_status: Annotated[DecisionStatus | None, Query(alias="status")] = None,
    owner: str | None = None,
    project: str | None = None,
    topic: str | None = None,
    review_state: SupportState | None = None,
) -> DecisionListResponse:
    return await service.list_decisions(
        status=decision_status.value if decision_status is not None else None,
        owner=owner,
        project=project,
        topic=topic,
        review_state=review_state,
        workspace_id=workspace.workspace_id,
    )


@router.get("/{decision_id}", response_model=DecisionDetail)
async def get_decision(
    decision_id: UUID,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DecisionService, Depends(get_decision_service)],
) -> DecisionDetail:
    return await service.get_decision(
        decision_id, workspace_id=workspace.workspace_id
    )


@router.patch("/{decision_id}", response_model=DecisionDetail)
async def correct_decision(
    decision_id: UUID,
    request: DecisionCorrectionRequest,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DecisionService, Depends(get_decision_service)],
) -> DecisionDetail:
    return await service.correct_decision(
        decision_id, request, workspace_id=workspace.workspace_id
    )


@router.post(
    "/{decision_id}/relations",
    response_model=DecisionRelationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_relation(
    decision_id: UUID,
    request: DecisionRelationRequest,
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[DecisionService, Depends(get_decision_service)],
) -> DecisionRelationResponse:
    return await service.create_relation(
        decision_id, request, workspace_id=workspace.workspace_id
    )
