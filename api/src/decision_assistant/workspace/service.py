from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.errors import ApplicationError
from decision_assistant.ingestion.models import Document
from decision_assistant.workspace.models import Workspace


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


class CorpusRebuildNotFound(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="corpus_rebuild_not_found",
            message="No corpus rebuild has run for this workspace",
            status_code=404,
            retryable=False,
        )


class CorpusRebuildNotRetryable(ApplicationError):
    def __init__(self, current_status: str) -> None:
        super().__init__(
            code="corpus_rebuild_not_retryable",
            message=(
                "A corpus rebuild can only be retried while the latest one "
                f"is failed (current status: {current_status})"
            ),
            status_code=409,
            retryable=False,
        )


class ProviderSwitchRequiresRebuild(ApplicationError):
    """FR-016: a profile-affecting provider change needs explicit confirmation.

    The 409 body carries the preview the UI needs (both profiles and how many documents would be
    re-ingested), not just a refusal.
    """

    def __init__(self, details: dict[str, Any]) -> None:
        super().__init__(
            code="provider_switch_requires_rebuild",
            message=(
                "Changing the embedding provider re-ingests every document in this workspace. "
                "Resubmit with confirm_rebuild: true to proceed."
            ),
            status_code=409,
            retryable=False,
            details=details,
        )


class ProviderSwitchNotConfigured(ApplicationError):
    """Refuses a switch to a provider the process could not actually call.

    Without this, an operator could persist a configuration whose credentials are missing and only
    discover it when the rebuild failed (DB43 aborts the whole rebuild), which is worse than a clear
    409 at switch time.
    """

    def __init__(self, generation_provider: str, embedding_provider: str) -> None:
        super().__init__(
            code="provider_switch_not_configured",
            message=(
                "The requested provider configuration is incomplete; set its credentials "
                "(for example GEMINI_API_KEY) before switching."
            ),
            status_code=409,
            retryable=False,
            details={
                "generation_provider": generation_provider,
                "embedding_provider": embedding_provider,
            },
        )


class CorpusRebuildInProgress(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="corpus_rebuild_in_progress",
            message=(
                "A corpus rebuild is already pending or running for a workspace in this "
                "installation; wait for it to finish before switching providers"
            ),
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

    async def acknowledge_provider_disclosure(
        self, workspace_id: UUID, *, owner_user_id: UUID
    ) -> Workspace:
        """Record the user's acknowledgement of the provider disclosure (T048, FR-014).

        Idempotent, and the first timestamp is kept rather than refreshed: the column answers
        "when did this user accept where their documents go?", which re-stamping on every call
        would make unanswerable.
        """
        workspace = await self.get(workspace_id, owner_user_id=owner_user_id)
        if workspace.disclosure_acknowledged_at is None:
            workspace.disclosure_acknowledged_at = datetime.now(UTC)
        return workspace

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

    async def document_counts_by_workspace(
        self, *, owner_user_id: UUID | None = None
    ) -> "list[tuple[Workspace, int]]":
        """Every workspace with its document count, in `list` order (DB57's switch preview).

        One grouped query rather than one per workspace, so the preview stays cheap as workspaces
        accumulate. The return annotation is quoted on purpose: `list` is also a method on this
        class, and a class body evaluates later annotations in a namespace where that method has
        already shadowed the builtin.
        """
        workspaces = await self.list(owner_user_id=owner_user_id)
        rows = await self._session.execute(
            select(Document.workspace_id, func.count(Document.id)).group_by(
                Document.workspace_id
            )
        )
        counts = {workspace_id: int(total) for workspace_id, total in rows}
        return [(workspace, counts.get(workspace.id, 0)) for workspace in workspaces]

    async def clear_provider_disclosure_acknowledgements(self) -> None:
        """Drop every workspace's acknowledgement (DB65).

        The provider choice is process-wide, so a switch that starts sending document text off the
        machine invalidates every acknowledgement, not only the addressed workspace's. Uploads stay
        blocked (`disclosure_not_acknowledged`) until each workspace is acknowledged again.
        """
        await self._session.execute(
            update(Workspace).values(disclosure_acknowledged_at=None)
        )
