from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.decisions.models import Decision
from decision_assistant.ingestion.models import Document, DocumentVersion, IngestionJob, Passage
from tests.support.document_fixtures import RecordingDispatcher, WORKSPACE_ID

# Re-exported so pytest can see it as a fixture of this module. It is requested
# as a parameter, never called, so the linter needs the explicit `as ...` form to
# recognise the import as a deliberate re-export (plain `import documents_api` is
# reported as unused and then shadowed — removing it silently breaks the fourteen
# tests that ask for the fixture; see M-067).
from tests.support.document_fixtures import documents_api as documents_api


async def _advance_created_at(session: AsyncSession, job_id: UUID) -> None:
    # `documents_api`'s fixture binds every request in a test to the same
    # long-lived `db_session`/transaction, unlike production's
    # one-session-per-request (`Depends(get_session)`) — so `created_at`'s
    # `server_default=func.now()` (transaction start time, not statement
    # time) ties between jobs created by different requests in the same
    # test. A real request boundary gives each job a genuinely later
    # `created_at`; this simulates that without an actual `commit()`, which
    # would defeat `db_session`'s test-isolating rollback.
    job = await session.get(IngestionJob, job_id)
    assert job is not None
    job.created_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    await session.flush()


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
                workspace_id=WORKSPACE_ID,
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


@pytest.mark.asyncio
async def test_retry_rejected_while_a_newer_job_is_already_in_flight(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    # V94: retrying against a stale `failed` job while a newer job (from an
    # earlier retry already in flight) exists must be rejected — otherwise
    # two concurrent ingestion jobs run against the same DocumentVersion.
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

    first_retry = await client.post(
        f'/api/v1/workspaces/{WORKSPACE_ID}/documents/{result["document_id"]}/retry',
        headers={"x-request-id": "retry-first"},
    )
    assert first_retry.status_code == 202
    assert len(dispatcher.calls) == 2  # original dispatch + first retry's
    await _advance_created_at(db_session, UUID(first_retry.json()["job_id"]))

    second_retry = await client.post(
        f'/api/v1/workspaces/{WORKSPACE_ID}/documents/{result["document_id"]}/retry',
        headers={"x-request-id": "retry-second"},
    )

    assert second_retry.status_code == 409
    assert second_retry.json()["code"] == "retry_not_available"
    # No new dispatch from the rejected second retry.
    assert len(dispatcher.calls) == 2


@pytest.mark.asyncio
async def test_document_detail_surfaces_failed_state_for_retry(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    # T024: GET /documents/{id} must surface the terminal `failed` state
    # (status/stage/progress/error) so the UI (T025) can render a retry
    # action from the detail view, not just the list.
    client, _, _ = documents_api
    upload = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("meeting.md", b"# Meeting\n", "text/markdown")},
    )
    result = upload.json()["results"][0]
    job = await db_session.get(IngestionJob, UUID(result["job_id"]))
    assert job is not None
    job.stage = "failed"
    job.status = "failed"
    job.progress = 40
    job.error = {"code": "provider_unavailable"}
    await db_session.flush()

    response = await client.get(
        f'/api/v1/workspaces/{WORKSPACE_ID}/documents/{result["document_id"]}'
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "failed"
    assert detail["stage"] == "failed"
    assert detail["progress"] == 40
    assert detail["error"] == {"code": "provider_unavailable"}


@pytest.mark.asyncio
async def test_document_detail_reports_pending_status_right_after_upload(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
) -> None:
    # A freshly uploaded document always has a job row (T022), so
    # `status`/`stage` are non-null from the very first read, before any
    # failure ever occurs.
    client, _, _ = documents_api
    upload = await client.post(
        "/api/v1/workspaces/{WORKSPACE_ID}/documents/upload",
        files={"files": ("brand-new.md", b"# Brand new\n", "text/markdown")},
    )
    document_id = upload.json()["results"][0]["document_id"]

    response = await client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/documents/{document_id}"
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "pending"


@pytest.mark.asyncio
async def test_document_detail_reflects_job_status_after_a_retry(
    documents_api: tuple[httpx.AsyncClient, RecordingDispatcher, Settings],
    db_session: AsyncSession,
) -> None:
    # V94 (frontend counterpart): the detail endpoint itself always reflects
    # the current latest job — proving the API side of "re-fetch the detail
    # after retry" (Workspace.tsx's `handleRetry`) actually has fresh data
    # to fetch, not stale `failed` state.
    client, _, _ = documents_api
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

    retry = await client.post(
        f'/api/v1/workspaces/{WORKSPACE_ID}/documents/{result["document_id"]}/retry',
    )
    assert retry.status_code == 202
    await _advance_created_at(db_session, UUID(retry.json()["job_id"]))

    response = await client.get(
        f'/api/v1/workspaces/{WORKSPACE_ID}/documents/{result["document_id"]}'
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "pending"
    assert detail["error"] is None
