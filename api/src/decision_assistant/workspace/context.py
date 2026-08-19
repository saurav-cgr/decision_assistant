from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.db import get_session
from decision_assistant.models import User
from decision_assistant.workspace.service import (
    WorkspaceService,
    WorkspaceStateError,
)


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    workspace_id: UUID


async def get_workspace_context(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkspaceContext:
    service = WorkspaceService(session)
    workspace = await service.get(
        workspace_id,
        owner_user_id=user.id,
    )  # raises 404 when missing
    if workspace.status == "archived":
        raise WorkspaceStateError(
            "Archived workspaces are not available for project operations"
        )
    return WorkspaceContext(workspace_id=workspace_id)
