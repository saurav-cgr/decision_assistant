from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.models import User, Workspace
from decision_assistant.workspace.context import get_workspace_context
from decision_assistant.workspace.service import WorkspaceNotFound


@pytest.mark.asyncio
async def test_workspace_context_rejects_a_non_owner(
    db_session: AsyncSession,
) -> None:
    owner = User(
        username=f"context-owner-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    other_user = User(
        username=f"context-other-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    db_session.add_all([owner, other_user])
    await db_session.flush()
    workspace = Workspace(owner_user_id=owner.id, name="Owner-only workspace")
    db_session.add(workspace)
    await db_session.flush()

    with pytest.raises(WorkspaceNotFound):
        await get_workspace_context(workspace.id, other_user, db_session)
