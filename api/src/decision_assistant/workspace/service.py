from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.models import Workspace


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, *, name: str = "Decision Assistant") -> Workspace:
        workspace = await self._session.scalar(
            select(Workspace).order_by(Workspace.created_at).limit(1)
        )
        if workspace is not None:
            return workspace

        workspace = Workspace(name=name, embedding_profile=None)
        self._session.add(workspace)
        await self._session.flush()
        return workspace
