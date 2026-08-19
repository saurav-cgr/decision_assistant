from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.documents.router import (
    _record_dispatch_failure,
    get_document_service,
)
from decision_assistant.documents.service import DocumentService
from decision_assistant.main import create_app
from decision_assistant.models import (
    Decision,
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
    Workspace,
)
from decision_assistant.providers.base import ProviderConfigurationInvalid
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)

WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def dispatch(
        self,
        *,
        document_id: object,
        job_id: object,
        source_path: Path,
        request_id: str,
    ) -> None:
        self.calls.append(
            {
                "document_id": document_id,
                "job_id": job_id,
                "source_path": source_path,
                "request_id": request_id,
            }
        )


@pytest.mark.asyncio
async def test_provider_creation_failure_marks_queued_job_and_version_failed(
    db_session: AsyncSession,
) -> None:
    document = Document(
        workspace_id=(await _workspace_id(db_session)),
        display_name="failed.md",
        media_type="text/markdown",
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        checksum="a" * 64,
        storage_path="failed.md",
        state="staging",
    )
    db_session.add(version)
    await db_session.flush()
    job = IngestionJob(
        document_id=document.id,
        document_version_id=version.id,
        stage="queued",
        status="pending",
        progress=0,
        attempt_count=0,
        request_id="provider-config-failure",
    )
    db_session.add(job)
    await db_session.flush()

    await _record_dispatch_failure(
        db_session,
        job.id,
        ProviderConfigurationInvalid(),
    )

    assert job.status == "failed"
    assert version.state == "failed"
    assert job.error == {
        "code": "provider_configuration_invalid",
        "message": "Model provider configuration is invalid",
        "retryable": False,
        "details": None,
    }


async def _workspace_id(session: AsyncSession) -> UUID:
    from decision_assistant.models import Workspace

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
    dispatcher = RecordingDispatcher()
    db_session.add(
        Workspace(
            id=WORKSPACE_ID,
            name=f"Documents workspace {WORKSPACE_ID}",
            embedding_profile=None,
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


@pytest.mark.asyncio
async def test_single_upload_is_sanitized_and_accepted(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
) -> None:
    client, dispatcher, settings = documents_api

    response = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("../../meeting.md", b"# Architecture\n", "text/markdown")},
        headers={"x-request-id": "upload-1"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["request_id"] == "upload-1"
    assert len(payload["results"]) == 1
    result = payload["results"][0]
    assert result["filename"] == "meeting.md"
    assert result["status"] == "accepted"
    assert result["error"] is None
    assert len(dispatcher.calls) == 1
    stored_path = dispatcher.calls[0]["source_path"]
    assert stored_path.is_relative_to(settings.upload_directory)
    assert stored_path.read_bytes() == b"# Architecture\n"


@pytest.mark.asyncio
async def test_multiple_valid_uploads_return_one_result_each(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
) -> None:
    client, dispatcher, _ = documents_api

    response = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files=[
            ("files", ("one.md", b"# One\n", "text/markdown")),
            ("files", ("two.txt", b"Decision two\n", "text/plain")),
        ],
    )

    assert response.status_code == 202
    assert [item["status"] for item in response.json()["results"]] == [
        "accepted",
        "accepted",
    ]
    assert len(dispatcher.calls) == 2


@pytest.mark.asyncio
async def test_invalid_extension_returns_per_file_error(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
) -> None:
    client, dispatcher, _ = documents_api

    response = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("malware.exe", b"unsafe", "application/octet-stream")},
    )

    assert response.status_code == 202
    result = response.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "unsupported_file_type"
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_excessive_size_returns_per_file_error(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
) -> None:
    client, dispatcher, settings = documents_api

    response = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={
            "files": (
                "large.txt",
                b"x" * (settings.max_upload_bytes + 1),
                "text/plain",
            )
        },
    )

    assert response.status_code == 202
    result = response.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "file_too_large"
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_mixed_upload_rejects_only_invalid_files(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
) -> None:
    client, dispatcher, _ = documents_api

    response = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files=[
            ("files", ("valid.md", b"# Valid\n", "text/markdown")),
            ("files", ("invalid.exe", b"bad", "application/octet-stream")),
        ],
    )

    assert response.status_code == 202
    results = response.json()["results"]
    assert [result["status"] for result in results] == ["accepted", "rejected"]
    assert results[1]["error"]["code"] == "unsupported_file_type"
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_document_listing_exposes_job_status_progress_and_error(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    client, _, _ = documents_api
    upload = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("meeting.md", b"# Meeting\n", "text/markdown")},
    )
    job_id = upload.json()["results"][0]["job_id"]
    job = await db_session.get(IngestionJob, UUID(job_id))
    assert job is not None
    job.status = "failed"
    job.stage = "embedding"
    job.progress = 40
    job.error = {"code": "provider_unavailable"}
    await db_session.flush()

    response = await client.get("/api/v1/workspaces/{WORKSPACE_ID}/documents")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "failed"
    assert item["stage"] == "embedding"
    assert item["progress"] == 40
    assert item["error"] == {"code": "provider_unavailable"}


@pytest.mark.asyncio
async def test_document_detail_and_listing_return_active_extraction(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    client, _, _ = documents_api
    upload = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("meeting.md", b"# Meeting\n", "text/markdown")},
    )
    document_id = upload.json()["results"][0]["document_id"]
    document = await db_session.get(Document, UUID(document_id))
    assert document is not None
    version = await db_session.scalar(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id)
    )
    assert version is not None
    version.state = "active"
    version.title = "Meeting"
    version.document_date = date(2026, 7, 15)
    version.participants = ["Asha", "Mateo"]
    version.source_type = "meeting_notes"
    version.project = "Atlas"
    version.normalized_content = "Authentication was postponed."
    document.active_version_id = version.id
    db_session.add_all(
        [
            Passage(
                document_version_id=version.id,
                sequence_number=0,
                content="Authentication was postponed.",
                start_offset=0,
                end_offset=30,
                content_hash="a" * 64,
                locator={"kind": "lines", "start": 1, "end": 1},
                embedding=[0.0] * 768,
            ),
            Decision(
                document_version_id=version.id,
                statement="Authentication was postponed.",
                status="active",
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/documents/{document.id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["active_version"]["title"] == "Meeting"
    assert detail["passages"] == [
        {
            "sequence_number": 0,
            "content": "Authentication was postponed.",
            "locator": {"kind": "lines", "start": 1, "end": 1},
            "structural_metadata": {},
        }
    ]

    listing = await client.get("/api/v1/workspaces/{WORKSPACE_ID}/documents")

    assert listing.status_code == 200
    summary = listing.json()["items"][0]
    assert summary["title"] == "Meeting"
    assert summary["document_date"] == "2026-07-15"
    assert summary["participants"] == ["Asha", "Mateo"]
    assert summary["source_type"] == "meeting_notes"
    assert summary["project"] == "Atlas"
    assert summary["modification_state"] == "new"
    assert summary["decision_count"] == 1


@pytest.mark.asyncio
async def test_failed_document_can_be_retried(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    client, dispatcher, _ = documents_api
    upload = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("meeting.md", b"# Meeting\n", "text/markdown")},
    )
    result = upload.json()["results"][0]
    job = await db_session.get(IngestionJob, UUID(result["job_id"]))
    assert job is not None
    job.status = "failed"
    job.error = {"code": "provider_unavailable"}
    await db_session.flush()

    response = await client.post(
        f'/api/v1/workspaces/{WORKSPACE_ID}/documents/{result["document_id"]}/retry',
        headers={"x-request-id": "retry-1"},
    )

    assert response.status_code == 202
    retry = response.json()
    assert retry["status"] == "accepted"
    assert retry["request_id"] == "retry-1"
    assert retry["job_id"] != result["job_id"]
    assert len(dispatcher.calls) == 2
