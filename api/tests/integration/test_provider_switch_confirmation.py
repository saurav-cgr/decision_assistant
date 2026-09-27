"""T047 (US6/FR-016): a provider switch that reshapes the corpus needs explicit confirmation.

The route is per workspace (authorization + the rebuild it triggers) while the provider choice itself
is stored globally (T050's `app_settings` row) — that asymmetry is deliberate and recorded; these
tests pin the behaviour that matters: a profile-affecting switch is refused with a preview until it is
confirmed, a confirmed switch is persisted **and** dispatches a rebuild, a switch that does not touch
the embedding profile needs no confirmation at all, and a switch to a provider this process cannot
call is refused instead of persisted.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.auth.models import User
from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.ingestion.models import Document
from decision_assistant.main import create_app
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.provider_config import (
    APP_SETTINGS_ID,
    AppSettings,
)
from decision_assistant.workspace.rebuild_models import CorpusRebuild

GEMINI_KEY = "fake-gemini-key-for-switch"


class _StubProviderBundleFactory:
    """Stands in for `CachedProviderBundleFactory` so no provider client is constructed."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def __call__(self) -> object:
        return object()

    async def aclose(self) -> None:
        return None


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    fields: dict[str, object] = {
        "upload_directory": tmp_path,
        "auth_jwt_secret": SecretStr("test-signing-secret-for-provider-switch"),
        "gemini_api_key": SecretStr(GEMINI_KEY),
        "generation_provider": "gemini",
        "embedding_provider": "gemini",
    }
    fields.update(overrides)
    return Settings(**fields)


@pytest_asyncio.fixture
async def switch_api(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]]]:
    import decision_assistant.workspace.router as router_module

    dispatches: list[object] = []

    async def _record_dispatch(*args: object, **kwargs: object) -> None:
        dispatches.append(kwargs)

    monkeypatch.setattr(router_module, "dispatch_pending_rebuild", _record_dispatch)
    monkeypatch.setattr(router_module, "CachedProviderBundleFactory", _StubProviderBundleFactory)

    owner = User(
        username=f"switch-owner-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    db_session.add(owner)
    await db_session.flush()
    workspace = Workspace(name=f"Switch {uuid4()}", owner_user_id=owner.id)
    db_session.add(workspace)
    await db_session.flush()

    settings = _settings(tmp_path)
    app = create_app(settings)
    app.state.provider_bundle_factory = _StubProviderBundleFactory(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, settings, owner, workspace, dispatches


def _url(workspace_id: UUID) -> str:
    return f"/api/v1/workspaces/{workspace_id}/provider"


async def _stored_config(session: AsyncSession) -> AppSettings | None:
    return await session.get(AppSettings, APP_SETTINGS_ID)


async def _rebuilds(session: AsyncSession, workspace_id: UUID) -> list[CorpusRebuild]:
    return list(
        await session.scalars(
            select(CorpusRebuild).where(CorpusRebuild.workspace_id == workspace_id)
        )
    )


async def test_profile_affecting_switch_returns_a_preview_and_changes_nothing(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    client, _settings_, _owner, workspace, dispatches = switch_api

    response = await client.post(
        _url(workspace.id),
        json={"generation_provider": "ollama", "embedding_provider": "ollama"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "provider_switch_requires_rebuild"
    details = body["details"]
    assert details["documents_total"] == 0
    assert details["current_embedding_profile"]["provider"] == "gemini"
    assert details["proposed_embedding_profile"]["provider"] == "ollama"
    # Nothing was persisted and nothing was dispatched: the refusal is the whole effect.
    assert await _stored_config(db_session) is None
    assert await _rebuilds(db_session, workspace.id) == []
    assert dispatches == []


async def test_confirmed_switch_is_persisted_and_dispatches_a_rebuild(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    client, settings, _owner, workspace, dispatches = switch_api

    response = await client.post(
        _url(workspace.id),
        json={
            "generation_provider": "ollama",
            "embedding_provider": "ollama",
            "confirm_rebuild": True,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["embedding_profile_changed"] is True
    assert body["rebuild"]["status"] == "pending"
    stored = await _stored_config(db_session)
    assert stored is not None
    assert (stored.generation_provider, stored.embedding_provider) == ("ollama", "ollama")
    # The in-process settings were updated too, or the dispatched rebuild would use the old provider.
    assert (settings.generation_provider, settings.embedding_provider) == ("ollama", "ollama")
    rebuilds = await _rebuilds(db_session, workspace.id)
    assert len(rebuilds) == 1
    assert rebuilds[0].reason == "provider_switch"
    assert len(dispatches) == 1


async def test_switch_without_a_profile_change_needs_no_confirmation(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    client, settings, _owner, workspace, dispatches = switch_api
    settings.generation_provider = "ollama"
    settings.embedding_provider = "ollama"

    # Only the generation provider changes: the embedding profile — the thing that decides whether
    # documents must be re-ingested — is untouched, so no rebuild is required.
    response = await client.post(
        _url(workspace.id),
        json={"generation_provider": "gemini", "embedding_provider": "ollama"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["embedding_profile_changed"] is False
    assert body["rebuild"] is None
    stored = await _stored_config(db_session)
    assert stored is not None
    assert stored.generation_provider == "gemini"
    assert await _rebuilds(db_session, workspace.id) == []
    assert dispatches == []


async def test_switch_to_an_unconfigured_provider_is_refused(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    client, settings, _owner, workspace, _dispatches = switch_api
    settings.generation_provider = "ollama"
    settings.embedding_provider = "ollama"
    settings.gemini_api_key = None

    response = await client.post(
        _url(workspace.id),
        json={
            "generation_provider": "gemini",
            "embedding_provider": "ollama",
            "confirm_rebuild": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "provider_switch_not_configured"
    assert await _stored_config(db_session) is None


async def test_unknown_provider_is_rejected_by_request_validation(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    client, _settings_, _owner, workspace, _dispatches = switch_api

    response = await client.post(
        _url(workspace.id),
        json={"generation_provider": "openai", "embedding_provider": "ollama"},
    )

    assert response.status_code == 422
    assert await _stored_config(db_session) is None


async def test_switch_is_refused_while_a_rebuild_is_active(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    client, _settings_, _owner, workspace, dispatches = switch_api
    db_session.add(
        CorpusRebuild(
            workspace_id=workspace.id,
            status="running",
            reason="corpus_reset_required",
            documents_total=2,
            documents_completed=0,
        )
    )
    await db_session.flush()

    response = await client.post(
        _url(workspace.id),
        json={
            "generation_provider": "ollama",
            "embedding_provider": "ollama",
            "confirm_rebuild": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "corpus_rebuild_in_progress"
    assert len(await _rebuilds(db_session, workspace.id)) == 1  # only the seeded one
    assert dispatches == []


async def test_another_users_workspace_cannot_be_switched(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, _owner, workspace, _dispatches = switch_api
    stranger = User(
        username=f"switch-stranger-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    db_session.add(stranger)
    await db_session.flush()

    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: stranger
    app.state.provider_bundle_factory = _StubProviderBundleFactory(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as stranger_client:
        response = await stranger_client.post(
            _url(workspace.id),
            json={
                "generation_provider": "ollama",
                "embedding_provider": "ollama",
                "confirm_rebuild": True,
            },
        )

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"
    assert await _stored_config(db_session) is None
    assert await _rebuilds(db_session, workspace.id) == []


async def test_switch_is_refused_while_another_workspace_is_rebuilding(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    """DB57: the guard is process-wide, because the stored provider choice is one global row."""
    client, _settings_, owner, workspace, dispatches = switch_api
    other = Workspace(name=f"Other {uuid4()}", owner_user_id=owner.id)
    db_session.add(other)
    await db_session.flush()
    db_session.add(
        CorpusRebuild(
            workspace_id=other.id,
            status="pending",
            reason="corpus_reset_required",
            documents_total=1,
            documents_completed=0,
        )
    )
    await db_session.flush()

    response = await client.post(
        _url(workspace.id),
        json={
            "generation_provider": "ollama",
            "embedding_provider": "ollama",
            "confirm_rebuild": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "corpus_rebuild_in_progress"
    assert await _stored_config(db_session) is None
    assert dispatches == []


async def test_preview_lists_the_document_count_of_every_workspace(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    """DB57: the preview must say the switch is process-wide, not about one workspace."""
    client, _settings_, owner, workspace, _dispatches = switch_api
    other = Workspace(name=f"Second {uuid4()}", owner_user_id=owner.id)
    db_session.add(other)
    await db_session.flush()
    db_session.add_all(
        [
            Document(
                workspace_id=workspace.id,
                display_name="a.md",
                media_type="text/markdown",
            ),
            Document(
                workspace_id=other.id,
                display_name="b.md",
                media_type="text/markdown",
            ),
            Document(
                workspace_id=other.id,
                display_name="c.md",
                media_type="text/markdown",
            ),
        ]
    )
    await db_session.flush()

    response = await client.post(
        _url(workspace.id),
        json={"generation_provider": "ollama", "embedding_provider": "ollama"},
    )

    assert response.status_code == 409
    details = response.json()["details"]
    assert details["documents_total"] == 1
    counts = {item["name"]: item["documents_total"] for item in details["workspaces"]}
    assert counts[workspace.name] == 1
    assert counts[other.name] == 2


async def test_switching_from_local_to_remote_clears_the_disclosure_acknowledgement(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
) -> None:
    """DB65: an ack for "text stays on this machine" does not survive a remote switch."""
    client, settings, _owner, workspace, _dispatches = switch_api
    settings.generation_provider = "ollama"
    settings.embedding_provider = "ollama"
    workspace.disclosure_acknowledged_at = datetime.now(UTC)
    await db_session.flush()

    response = await client.post(
        _url(workspace.id),
        json={
            "generation_provider": "gemini",
            "embedding_provider": "gemini",
            "confirm_rebuild": True,
        },
    )

    assert response.status_code == 202
    assert response.json()["disclosure_acknowledgement_cleared"] is True
    await db_session.refresh(workspace)
    assert workspace.disclosure_acknowledged_at is None


async def test_switch_route_takes_the_process_wide_lock(
    switch_api: tuple[httpx.AsyncClient, Settings, User, Workspace, list[object]],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB72(b): the DB68 guard is real only if the route actually takes the lock.

    `test_provider_switch_lock.py` pins the primitive; this test pins the call site. Deleting
    `acquire_provider_switch_lock(session)` from `workspace/router.py` would leave every test in
    that file green, so nothing else in the suite would notice the DB68 race coming back.
    """
    import decision_assistant.workspace.router as router_module
    from decision_assistant.workspace.provider_config import (
        acquire_provider_switch_lock as real_lock,
    )

    locked: list[AsyncSession] = []

    async def _spy(session: AsyncSession) -> None:
        locked.append(session)
        await real_lock(session)

    monkeypatch.setattr(router_module, "acquire_provider_switch_lock", _spy)

    client, settings, _owner, workspace, _dispatches = switch_api
    settings.generation_provider = "ollama"
    settings.embedding_provider = "ollama"

    # A generation-only switch is enough: the lock is taken before the rebuild guard, so it is on
    # every path through this route, not only a profile-affecting one.
    response = await client.post(
        _url(workspace.id),
        json={"generation_provider": "gemini", "embedding_provider": "ollama"},
    )

    assert response.status_code == 200
    assert locked == [db_session], (
        "the switch route did not take the process-wide provider-switch lock, so two switches "
        "arriving together could both pass the rebuild guard (DB68/DB72)"
    )
