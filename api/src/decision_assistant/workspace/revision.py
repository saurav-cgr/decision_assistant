from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.models import Workspace


async def bump_knowledge_revision(
    session: AsyncSession,
    workspace_id: UUID,
) -> None:
    await session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(knowledge_revision=Workspace.knowledge_revision + 1)
    )
