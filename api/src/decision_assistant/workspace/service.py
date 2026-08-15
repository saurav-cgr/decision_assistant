from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.errors import ApplicationError
from decision_assistant.models import Document, Workspace


class WorkspaceConflict(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="workspace_name_conflict",
            message="A workspace with that name already exists",
            status_code=409,
            retryable=False,
        )


class WorkspaceNotFound(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="workspace_not_found",
            message="Workspace not found",
            status_code=404,
            retryable=False,
        )


class WorkspaceStateError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="workspace_state_error",
            message=message,
            status_code=409,
            retryable=False,
        )


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str) -> Workspace:
        existing = await self._session.scalar(
            select(Workspace).where(Workspace.name == name)
        )
        if existing is not None:
            raise WorkspaceConflict()
        workspace = Workspace(name=name, embedding_profile=None)
        # The first workspace becomes the active workspace.
        any_workspace = await self._session.scalar(select(Workspace.id).limit(1))
        workspace.is_active = any_workspace is None
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def list(self) -> list[Workspace]:
        return list(
            await self._session.scalars(
                select(Workspace).order_by(Workspace.created_at)
            )
        )

    async def get(self, workspace_id: UUID) -> Workspace:
        workspace = await self._session.get(Workspace, workspace_id)
        if workspace is None:
            raise WorkspaceNotFound()
        return workspace

    async def get_active(self) -> Workspace | None:
        workspace = await self._session.scalar(
            select(Workspace).where(Workspace.is_active.is_(True))
        )
        if workspace is not None:
            return workspace
        return await self._session.scalar(
            select(Workspace).order_by(Workspace.created_at).limit(1)
        )

    async def get_or_create_active(self, *, name: str = "Decision Assistant") -> Workspace:
        workspace = await self.get_active()
        if workspace is not None:
            return workspace
        return await self.create(name=name)

    async def rename(self, workspace_id: UUID, name: str) -> Workspace:
        workspace = await self.get(workspace_id)
        duplicate = await self._session.scalar(
            select(Workspace).where(
                Workspace.name == name,
                Workspace.id != workspace_id,
            )
        )
        if duplicate is not None:
            raise WorkspaceConflict()
        workspace.name = name
        await self._session.flush()
        return workspace

    async def activate(self, workspace_id: UUID) -> Workspace:
        workspace = await self.get(workspace_id)
        if workspace.status == "archived":
            raise WorkspaceStateError("An archived workspace cannot be activated")
        await self._session.execute(update(Workspace).values(is_active=False))
        workspace.is_active = True
        await self._session.flush()
        return workspace

    async def archive(self, workspace_id: UUID) -> Workspace:
        workspace = await self.get(workspace_id)
        if workspace.is_active:
            raise WorkspaceStateError(
                "The active workspace cannot be archived; activate another first"
            )
        if workspace.status == "archived":
            raise WorkspaceStateError("Workspace is already archived")
        workspace.status = "archived"
        await self._session.flush()
        return workspace

    async def delete_archived(self, workspace_id: UUID) -> None:
        workspace = await self.get(workspace_id)
        if workspace.status != "archived":
            raise WorkspaceStateError("Only archived workspaces can be deleted")
        if workspace.is_active:
            raise WorkspaceStateError("The active workspace cannot be deleted")
        await self._session.delete(workspace)
        await self._session.flush()

    async def document_count(self, workspace_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count(Document.id)).where(
                Document.workspace_id == workspace_id
            )
        )
        return int(count or 0)
