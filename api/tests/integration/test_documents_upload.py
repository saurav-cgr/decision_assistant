from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.documents.router import _record_dispatch_failure
from decision_assistant.ingestion.models import Document, DocumentVersion, IngestionJob
from decision_assistant.providers.base import ProviderConfigurationInvalid
from tests.support.document_fixtures import (
    RecordingDispatcher,
    WORKSPACE_ID,
    _workspace_id,
)

# Re-exported so pytest can see it as a fixture of this module; the explicit
# `as ...` form is what marks it as a deliberate re-export for the linter.
from tests.support.document_fixtures import documents_api as documents_api


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
    # T022: the IngestionJob row backing this dispatch must already exist
    # (as `pending`) by the time `background_tasks.add_task` fires — that
    # row is what a startup-sweep restart (T021/DB27) needs to find if the
    # process dies before this dispatch ever runs.
    assert dispatcher.job_status_at_dispatch == ["pending"]


@pytest.mark.asyncio
async def test_retry_dispatch_has_a_persisted_pending_job_row(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    # T022, retry path: same invariant as the upload path, verified for
    # `DocumentService.retry`'s dispatch too.
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
        headers={"x-request-id": "retry-pending-check"},
    )

    assert response.status_code == 202
    assert dispatcher.job_status_at_dispatch == ["pending", "pending"]


@pytest.mark.asyncio
async def test_same_file_under_new_name_is_accepted_as_duplicate(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    client, dispatcher, settings = documents_api
    content = b"# Architecture\n"

    first_response = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("original.md", content, "text/markdown")},
    )
    first_result = first_response.json()["results"][0]
    document = await db_session.get(Document, UUID(first_result["document_id"]))
    assert document is not None
    version = await db_session.scalar(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id)
    )
    assert version is not None
    version.state = "active"
    document.active_version_id = version.id
    await db_session.flush()

    second_response = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("renamed.md", content, "text/markdown")},
    )

    assert second_response.status_code == 202
    result = second_response.json()["results"][0]
    assert result["status"] == "accepted"
    assert result["document_id"] == str(document.id)
    assert result["duplicate_of_document_id"] == str(document.id)
    assert result["duplicate_of_version_id"] == str(version.id)
    assert len(dispatcher.calls) == 1
    incoming = list((settings.upload_directory / "documents").glob("*/incoming/*"))
    assert incoming == [dispatcher.calls[0]["source_path"]]
    job = await db_session.get(IngestionJob, UUID(result["job_id"]))
    assert job is not None
    assert job.document_version_id == version.id
    assert job.stage == "unchanged"
    assert job.status == "completed"


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
