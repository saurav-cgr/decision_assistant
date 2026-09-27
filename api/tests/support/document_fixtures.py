"""Shared fixtures for the documents API test suite (test_documents_upload.py,
test_documents_detail.py). Split out of what used to be a single
test_documents_api.py once it grew past the 500-line file-size cap
(AGENTS.md); kept here rather than a bare `conftest.py` so the fixtures'
document-specific purpose stays obvious to anyone importing them.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from decision_assistant.config import Settings
from decision_assistant.documents.router import get_document_service
from decision_assistant.documents.service import DocumentService
from decision_assistant.ingestion.models import IngestionJob
from decision_assistant.main import create_app
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")


class RecordingDispatcher:
    def __init__(self, *, session: AsyncSession | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        # T022: when supplied, each call snapshots the IngestionJob row's
        # `status` as read at dispatch time — before this stub does anything
        # else — proving the row the startup sweep (T021/DB27) would need
        # was already committed and visible, not created only afterward.
        self._session = session
        self.job_status_at_dispatch: list[str | None] = []

    async def dispatch(
        self,
        *,
        document_id: object,
        job_id: object,
        source_path: Path,
        request_id: str,
    ) -> None:
        if self._session is not None:
            job = await self._session.get(IngestionJob, job_id)
            self.job_status_at_dispatch.append(job.status if job is not None else None)
        self.calls.append(
            {
                "document_id": document_id,
                "job_id": job_id,
                "source_path": source_path,
                "request_id": request_id,
            }
        )


async def _workspace_id(session: AsyncSession) -> UUID:
    workspace = Workspace(name="failure-workspace", embedding_profile=None)
    session.add(workspace)
    await session.flush()
    return workspace.id


@pytest_asyncio.fixture
async def documents_api(
    db_session: AsyncSession,
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, RecordingDispatcher, Settings]]:
    settings = Settings(
        upload_directory=tmp_path / "uploads",
        max_upload_bytes=64,
    )
    dispatcher = RecordingDispatcher(session=db_session)
    db_session.add(
        Workspace(
            id=WORKSPACE_ID,
            name=f"Documents workspace {WORKSPACE_ID}",
            embedding_profile=None,
            # Pre-acknowledged: these tests are about upload mechanics, retention and retry, not
            # about the FR-014 disclosure gate. `test_provider_disclosure.py` owns that gate and
            # drives it through the real route (T046/T049).
            disclosure_acknowledged_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
    service = DocumentService(
        session=db_session,
        settings=settings,
        dispatcher=dispatcher,
    )
    app = create_app(settings)

    async def override_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_service
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, dispatcher, settings
