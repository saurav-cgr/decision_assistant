"""T048 (US6/FR-014): the provider disclosure a user reads before their first upload.

The disclosure has to answer two questions honestly — which provider is active, and whether
document text leaves this machine — and it has to be per-workspace and owner-scoped, because the
answer depends on the workspace's configuration, not on a global setting. The upload guard that
depends on the acknowledgement is T049 and is covered separately.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.auth.models import User
from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.documents.router import get_document_service
from decision_assistant.documents.service import DocumentService
from decision_assistant.ingestion.models import Document
from decision_assistant.main import create_app
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)
from decision_assistant.workspace.models import Workspace
from tests.support.document_fixtures import RecordingDispatcher


@asynccontextmanager
async def _client(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    workspace_id: UUID | None = None,
    document_service: DocumentService | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: user
    if workspace_id is not None:
        app.dependency_overrides[get_workspace_context] = lambda: WorkspaceContext(
            workspace_id=workspace_id
        )
    if document_service is not None:
        app.dependency_overrides[get_document_service] = lambda: document_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def _owner(session: AsyncSession) -> User:
    user = User(
        username=f"disclosure-owner-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    session.add(user)
    await session.flush()
    return user


async def _workspace(session: AsyncSession, owner: User, name: str) -> Workspace:
    workspace = Workspace(name=f"{name} {uuid4()}", owner_user_id=owner.id)
    session.add(workspace)
    await session.flush()
    return workspace


def _url(workspace_id: UUID) -> str:
    return f"/api/v1/workspaces/{workspace_id}/provider-disclosure"


async def test_disclosure_reports_the_remote_default_before_acknowledgement(
    db_session: AsyncSession,
) -> None:
    owner = await _owner(db_session)
    workspace = await _workspace(db_session, owner, "Remote")

    async with _client(
        db_session,
        Settings(generation_provider="gemini", embedding_provider="gemini"),
        owner,
    ) as client:
        response = await client.get(_url(workspace.id))

    assert response.status_code == 200
    assert response.json() == {
        "provider": "gemini",
        "generation_provider": "gemini",
        "embedding_provider": "gemini",
        "generation_sends_document_text_remotely": True,
        "embedding_sends_document_text_remotely": True,
        "sends_document_text_remotely": True,
        "acknowledged_at": None,
    }


async def test_acknowledgement_is_recorded_and_idempotent(db_session: AsyncSession) -> None:
    owner = await _owner(db_session)
    workspace = await _workspace(db_session, owner, "Ack")

    async with _client(
        db_session,
        Settings(generation_provider="gemini", embedding_provider="gemini"),
        owner,
    ) as client:
        first = await client.post(f"{_url(workspace.id)}/ack")
        second = await client.post(f"{_url(workspace.id)}/ack")

    assert first.status_code == 200
    assert first.json()["acknowledged_at"] is not None
    # Idempotent, and the first acknowledgement is the one recorded: re-stamping on every call
    # would make "when did this user accept where their documents go?" unanswerable.
    assert second.json()["acknowledged_at"] == first.json()["acknowledged_at"]


async def test_offline_configuration_reports_no_remote_text(db_session: AsyncSession) -> None:
    owner = await _owner(db_session)
    workspace = await _workspace(db_session, owner, "Offline")

    async with _client(
        db_session,
        Settings(generation_provider="ollama", embedding_provider="ollama"),
        owner,
    ) as client:
        response = await client.get(_url(workspace.id))

    assert response.status_code == 200
    assert response.json()["provider"] == "ollama"
    assert response.json()["generation_provider"] == "ollama"
    assert response.json()["embedding_provider"] == "ollama"
    assert response.json()["generation_sends_document_text_remotely"] is False
    assert response.json()["embedding_sends_document_text_remotely"] is False
    assert response.json()["sends_document_text_remotely"] is False


async def test_mixed_configuration_is_remote_when_either_provider_is_remote(
    db_session: AsyncSession,
) -> None:
    owner = await _owner(db_session)
    # Document text is embedded as well as answered, so a local generation provider does not make
    # the workspace offline while the embedding provider is remote.
    workspace = await _workspace(db_session, owner, "Mixed")

    async with _client(
        db_session,
        Settings(generation_provider="ollama", embedding_provider="gemini"),
        owner,
    ) as client:
        response = await client.get(_url(workspace.id))

    assert response.json()["provider"] == "ollama"
    assert response.json()["generation_provider"] == "ollama"
    assert response.json()["embedding_provider"] == "gemini"
    # The per-provider flags are what let the disclosure name the correct destination: the search
    # index goes to Gemini, while answers are generated locally (V146's mixed-configuration break).
    assert response.json()["generation_sends_document_text_remotely"] is False
    assert response.json()["embedding_sends_document_text_remotely"] is True
    assert response.json()["sends_document_text_remotely"] is True


async def test_unknown_provider_name_fails_toward_disclosure(
    db_session: AsyncSession,
) -> None:
    owner = await _owner(db_session)
    workspace = await _workspace(db_session, owner, "Unknown")

    # Only providers known to be offline count as offline; anything unrecognised is disclosed as
    # remote, so a future provider cannot ship without a disclosure by default.
    async with _client(
        db_session,
        Settings(generation_provider="some-future-provider", embedding_provider="ollama"),
        owner,
    ) as client:
        response = await client.get(_url(workspace.id))

    assert response.json() == {
        "provider": "some-future-provider",
        "generation_provider": "some-future-provider",
        "embedding_provider": "ollama",
        "generation_sends_document_text_remotely": True,
        "embedding_sends_document_text_remotely": False,
        "sends_document_text_remotely": True,
        "acknowledged_at": None,
    }


async def test_another_users_workspace_is_not_readable_or_acknowledgeable(
    db_session: AsyncSession,
) -> None:
    owner = await _owner(db_session)
    stranger = await _owner(db_session)
    workspace = await _workspace(db_session, owner, "Private")

    async with _client(
        db_session,
        Settings(generation_provider="gemini", embedding_provider="gemini"),
        stranger,
    ) as client:
        read = await client.get(_url(workspace.id))
        acknowledge = await client.post(f"{_url(workspace.id)}/ack")

    assert read.status_code == 404
    assert read.json()["code"] == "workspace_not_found"
    # The write path is scoped too, not just the read: acknowledging someone else's workspace
    # would otherwise let an attacker satisfy the FR-014 guard on a workspace they do not own.
    assert acknowledge.status_code == 404
    assert acknowledge.json()["code"] == "workspace_not_found"
    assert workspace.disclosure_acknowledged_at is None


async def test_unknown_workspace_is_not_found(db_session: AsyncSession) -> None:
    owner = await _owner(db_session)

    async with _client(
        db_session,
        Settings(generation_provider="gemini", embedding_provider="gemini"),
        owner,
    ) as client:
        response = await client.get(_url(uuid4()))

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def _upload_url(workspace_id: UUID) -> str:
    return f"/api/v1/workspaces/{workspace_id}/documents/upload"


def _upload_files() -> dict[str, tuple[str, bytes, str]]:
    return {"files": ("notes.md", b"# Heading\n\nSome prose.\n", "text/markdown")}


async def _document_count(session: AsyncSession, workspace_id: UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.workspace_id == workspace_id)
        )
        or 0
    )


async def test_upload_is_refused_until_the_disclosure_is_acknowledged(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    # T046/FR-014: this is the whole point of the acknowledgement — the upload route 409s until it
    # exists, and the refusal must not leave anything behind (no Document row, so no ingestion job).
    owner = await _owner(db_session)
    workspace = await _workspace(db_session, owner, "Upload gate")
    settings = Settings(upload_directory=tmp_path / "uploads")
    service = DocumentService(
        session=db_session,
        settings=settings,
        dispatcher=RecordingDispatcher(),
    )

    async with _client(
        db_session,
        settings,
        owner,
        workspace_id=workspace.id,
        document_service=service,
    ) as client:
        refused = await client.post(_upload_url(workspace.id), files=_upload_files())

        assert refused.status_code == 409
        assert refused.json()["code"] == "disclosure_not_acknowledged"
        assert await _document_count(db_session, workspace.id) == 0

        acknowledged = await client.post(f"{_url(workspace.id)}/ack")
        assert acknowledged.status_code == 200

        accepted = await client.post(_upload_url(workspace.id), files=_upload_files())

    assert accepted.status_code == 202
    assert accepted.json()["results"][0]["status"] == "accepted"
    assert workspace.disclosure_acknowledged_at is not None
    assert await _document_count(db_session, workspace.id) == 1


async def test_upload_is_refused_when_the_workspace_belongs_to_someone_else(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    # The gate must not be a way to probe another user's workspace. Note this test deliberately does
    # NOT override `get_workspace_context`: the real dependency is what enforces ownership (it 404s
    # for a non-owner), and overriding it away would let the upload reach the disclosure check and
    # answer 409 — which would both be a wrong assertion and hide the fact that ownership is the
    # route dependency's job.
    owner = await _owner(db_session)
    stranger = await _owner(db_session)
    workspace = await _workspace(db_session, owner, "Not yours")
    settings = Settings(upload_directory=tmp_path / "uploads")
    service = DocumentService(
        session=db_session,
        settings=settings,
        dispatcher=RecordingDispatcher(),
    )

    async with _client(
        db_session,
        settings,
        stranger,
        document_service=service,
    ) as client:
        refused = await client.post(_upload_url(workspace.id), files=_upload_files())

    assert refused.status_code == 404
    assert refused.json()["code"] == "workspace_not_found"
    assert await _document_count(db_session, workspace.id) == 0
