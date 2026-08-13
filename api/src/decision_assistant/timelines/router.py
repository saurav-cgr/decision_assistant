from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.db import get_session
from decision_assistant.timelines.schemas import TimelineResponse
from decision_assistant.timelines.service import TimelineService
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/timelines", tags=["timelines"]
)


def get_timeline_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TimelineService:
    return TimelineService(session)


@router.get("", response_model=TimelineResponse)
async def get_timeline(
    workspace: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    service: Annotated[TimelineService, Depends(get_timeline_service)],
    topic: Annotated[str, Query(min_length=1)],
) -> TimelineResponse:
    return await service.build_timeline(
        topic, workspace_id=workspace.workspace_id
    )
