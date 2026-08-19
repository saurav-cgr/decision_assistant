from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.db import get_session
from decision_assistant.main import create_app
from decision_assistant.models import User, Workspace

MISSING_UUID = "00000000-0000-0000-0000-000000000000"


@pytest_asyncio.fixture
async def workspace_api(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    # Clear any workspace auto-created by other tests via the shared session so
    # each workspace test starts from an empty corpus (first = active).
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.flush()
    owner = User(
        username=f"workspace-owner-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    db_session.add(owner)
    await db_session.flush()

    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def _create(client: httpx.AsyncClient, name: str) -> dict:
    response = await client.post("/api/v1/workspaces", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def test_first_workspace_is_active(workspace_api: httpx.AsyncClient) -> None:
    body = await _create(workspace_api, "Atlas")
    assert body["name"] == "Atlas"
    assert body["status"] == "active"
    assert body["is_active"] is True


async def test_second_workspace_is_not_active(workspace_api: httpx.AsyncClient) -> None:
    await _create(workspace_api, "Atlas")
    body = await _create(workspace_api, "Apollo")
    assert body["is_active"] is False


async def test_duplicate_name_returns_conflict(workspace_api: httpx.AsyncClient) -> None:
    await _create(workspace_api, "Atlas")
    response = await workspace_api.post("/api/v1/workspaces", json={"name": "Atlas"})
    assert response.status_code == 409
    assert response.json()["code"] == "workspace_name_conflict"


async def test_duplicate_name_is_case_insensitive(
    workspace_api: httpx.AsyncClient,
) -> None:
    await _create(workspace_api, "Atlas")
    response = await workspace_api.post("/api/v1/workspaces", json={"name": "atlas"})
    assert response.status_code == 409


async def test_list_returns_all_workspaces(workspace_api: httpx.AsyncClient) -> None:
    await _create(workspace_api, "Atlas")
    await _create(workspace_api, "Apollo")
    response = await workspace_api.get("/api/v1/workspaces")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["items"]}
    assert names == {"Atlas", "Apollo"}


async def test_rename_workspace(workspace_api: httpx.AsyncClient) -> None:
    created = await _create(workspace_api, "Atlas")
    response = await workspace_api.patch(
        f"/api/v1/workspaces/{created['id']}", json={"name": "Atlas2"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Atlas2"


async def test_rename_to_duplicate_returns_conflict(
    workspace_api: httpx.AsyncClient,
) -> None:
    a = await _create(workspace_api, "A")
    await _create(workspace_api, "B")
    response = await workspace_api.patch(
        f"/api/v1/workspaces/{a['id']}", json={"name": "B"}
    )
    assert response.status_code == 409


async def test_activate_switches_single_active(
    workspace_api: httpx.AsyncClient,
) -> None:
    await _create(workspace_api, "A")
    b = await _create(workspace_api, "B")
    response = await workspace_api.post(f"/api/v1/workspaces/{b['id']}/activate")
    assert response.status_code == 200
    listing = (await workspace_api.get("/api/v1/workspaces")).json()["items"]
    active = [item for item in listing if item["is_active"]]
    assert [item["name"] for item in active] == ["B"]


async def test_archive_rejects_active_workspace(
    workspace_api: httpx.AsyncClient,
) -> None:
    a = await _create(workspace_api, "A")
    response = await workspace_api.post(f"/api/v1/workspaces/{a['id']}/archive")
    assert response.status_code == 409
    assert response.json()["code"] == "workspace_state_error"


async def test_archive_non_active_workspace(
    workspace_api: httpx.AsyncClient,
) -> None:
    await _create(workspace_api, "A")
    b = await _create(workspace_api, "B")
    response = await workspace_api.post(f"/api/v1/workspaces/{b['id']}/archive")
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


async def test_delete_rejects_non_archived(workspace_api: httpx.AsyncClient) -> None:
    a = await _create(workspace_api, "A")
    response = await workspace_api.delete(f"/api/v1/workspaces/{a['id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "workspace_state_error"


async def test_delete_archived_workspace(workspace_api: httpx.AsyncClient) -> None:
    await _create(workspace_api, "A")
    b = await _create(workspace_api, "B")
    await workspace_api.post(f"/api/v1/workspaces/{b['id']}/archive")
    response = await workspace_api.delete(f"/api/v1/workspaces/{b['id']}")
    assert response.status_code == 204
    listing = (await workspace_api.get("/api/v1/workspaces")).json()["items"]
    assert len(listing) == 1


async def test_get_missing_workspace_returns_not_found(
    workspace_api: httpx.AsyncClient,
) -> None:
    response = await workspace_api.get(f"/api/v1/workspaces/{MISSING_UUID}")
    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


async def test_workspace_routes_reject_anonymous_requests(
    db_session: AsyncSession,
) -> None:
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/workspaces")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


async def test_workspace_routes_hide_other_users_workspaces(
    db_session: AsyncSession,
) -> None:
    owner = User(
        username=f"owner-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    other_user = User(
        username=f"other-user-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    db_session.add_all([owner, other_user])
    await db_session.flush()
    workspace = Workspace(owner_user_id=owner.id, name="Private workspace")
    db_session.add(workspace)
    await db_session.flush()
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: other_user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/workspaces/{workspace.id}")

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"
