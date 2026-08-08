from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.documents.router import get_document_service
from decision_assistant.documents.service import DocumentService
from decision_assistant.main import create_app
from decision_assistant.models import Document, DocumentVersion, IngestionJob, Passage


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
    service = DocumentService(
        session=db_session,
        settings=settings,
        dispatcher=dispatcher,
    )
    app = create_app(settings)

    async def override_service() -> DocumentService:
        return service

    app.dependency_overrides[get_document_service] = override_service
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
        "/api/v1/documents/upload",
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
        "/api/v1/documents/upload",
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
        "/api/v1/documents/upload",
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
        "/api/v1/documents/upload",
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
        "/api/v1/documents/upload",
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
        "/api/v1/documents/upload",
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

    response = await client.get("/api/v1/documents")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "failed"
    assert item["stage"] == "embedding"
    assert item["progress"] == 40
    assert item["error"] == {"code": "provider_unavailable"}


@pytest.mark.asyncio
async def test_document_detail_returns_active_passages(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    client, _, _ = documents_api
    upload = await client.post(
        "/api/v1/documents/upload",
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
    version.normalized_content = "Authentication was postponed."
    document.active_version_id = version.id
    db_session.add(
        Passage(
            document_version_id=version.id,
            sequence_number=0,
            content="Authentication was postponed.",
            start_offset=0,
            end_offset=30,
            content_hash="a" * 64,
            locator={"kind": "lines", "start": 1, "end": 1},
            embedding=[0.0] * 768,
        )
    )
    await db_session.flush()

    response = await client.get(f"/api/v1/documents/{document.id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["active_version"]["title"] == "Meeting"
    assert detail["passages"] == [
        {
            "sequence_number": 0,
            "content": "Authentication was postponed.",
            "locator": {"kind": "lines", "start": 1, "end": 1},
        }
    ]


@pytest.mark.asyncio
async def test_failed_document_can_be_retried(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    client, dispatcher, _ = documents_api
    upload = await client.post(
        "/api/v1/documents/upload",
        files={"files": ("meeting.md", b"# Meeting\n", "text/markdown")},
    )
    result = upload.json()["results"][0]
    job = await db_session.get(IngestionJob, UUID(result["job_id"]))
    assert job is not None
    job.status = "failed"
    job.error = {"code": "provider_unavailable"}
    await db_session.flush()

    response = await client.post(
        f'/api/v1/documents/{result["document_id"]}/retry',
        headers={"x-request-id": "retry-1"},
    )

    assert response.status_code == 202
    retry = response.json()
    assert retry["status"] == "accepted"
    assert retry["request_id"] == "retry-1"
    assert retry["job_id"] != result["job_id"]
    assert len(dispatcher.calls) == 2
