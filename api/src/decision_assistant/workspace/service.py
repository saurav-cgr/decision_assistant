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

    async def create(
        self,
        *,
        owner_user_id: UUID | None = None,
        name: str,
    ) -> Workspace:
        statement = select(Workspace).where(Workspace.name == name)
        if owner_user_id is not None:
            statement = statement.where(Workspace.owner_user_id == owner_user_id)
        existing = await self._session.scalar(statement)
        if existing is not None:
            raise WorkspaceConflict()
        workspace = Workspace(
            owner_user_id=owner_user_id,
            name=name,
            embedding_profile=None,
        )
        # The first workspace becomes the active workspace.
        any_workspace = await self._session.scalar(
            select(Workspace.id)
            .where(Workspace.owner_user_id == owner_user_id)
            .limit(1)
        )
        workspace.is_active = any_workspace is None
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def list(self, *, owner_user_id: UUID | None = None) -> list[Workspace]:
        statement = select(Workspace)
        if owner_user_id is not None:
            statement = statement.where(Workspace.owner_user_id == owner_user_id)
        return list(
            await self._session.scalars(
                statement.order_by(Workspace.created_at)
            )
        )

    async def get(
        self,
        workspace_id: UUID,
        *,
        owner_user_id: UUID | None = None,
    ) -> Workspace:
        statement = select(Workspace).where(Workspace.id == workspace_id)
        if owner_user_id is not None:
            statement = statement.where(Workspace.owner_user_id == owner_user_id)
        workspace = await self._session.scalar(statement)
        if workspace is None:
            raise WorkspaceNotFound()
        return workspace

    async def get_active(self, *, owner_user_id: UUID | None = None) -> Workspace | None:
        statement = select(Workspace).where(Workspace.is_active.is_(True))
        if owner_user_id is not None:
            statement = statement.where(Workspace.owner_user_id == owner_user_id)
        workspace = await self._session.scalar(statement)
        if workspace is not None:
            return workspace
        fallback = select(Workspace).order_by(Workspace.created_at).limit(1)
        if owner_user_id is not None:
            fallback = fallback.where(Workspace.owner_user_id == owner_user_id)
        return await self._session.scalar(fallback)

    async def get_or_create_active(
        self,
        *,
        owner_user_id: UUID | None = None,
        name: str = "Decision Assistant",
    ) -> Workspace:
        workspace = await self.get_active(owner_user_id=owner_user_id)
        if workspace is not None:
            return workspace
        return await self.create(owner_user_id=owner_user_id, name=name)

    async def rename(self, workspace_id: UUID, *, owner_user_id: UUID, name: str) -> Workspace:
        workspace = await self.get(workspace_id, owner_user_id=owner_user_id)
        duplicate = await self._session.scalar(
            select(Workspace).where(
                Workspace.owner_user_id == owner_user_id,
                Workspace.name == name,
                Workspace.id != workspace_id,
            )
        )
        if duplicate is not None:
            raise WorkspaceConflict()
        workspace.name = name
        await self._session.flush()
        return workspace

    async def activate(self, workspace_id: UUID, *, owner_user_id: UUID) -> Workspace:
        workspace = await self.get(workspace_id, owner_user_id=owner_user_id)
        if workspace.status == "archived":
            raise WorkspaceStateError("An archived workspace cannot be activated")
        await self._session.execute(
            update(Workspace)
            .where(Workspace.owner_user_id == owner_user_id)
            .values(is_active=False)
        )
        workspace.is_active = True
        await self._session.flush()
        return workspace

    async def archive(self, workspace_id: UUID, *, owner_user_id: UUID) -> Workspace:
        workspace = await self.get(workspace_id, owner_user_id=owner_user_id)
        if workspace.is_active:
            raise WorkspaceStateError(
                "The active workspace cannot be archived; activate another first"
            )
        if workspace.status == "archived":
            raise WorkspaceStateError("Workspace is already archived")
        workspace.status = "archived"
        await self._session.flush()
        return workspace

    async def delete_archived(self, workspace_id: UUID, *, owner_user_id: UUID) -> None:
        workspace = await self.get(workspace_id, owner_user_id=owner_user_id)
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
