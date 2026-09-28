from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.db import get_session
from decision_assistant.main import create_app
from decision_assistant.auth.models import User
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.rebuild_models import CorpusRebuild

MISSING_UUID = "00000000-0000-0000-0000-000000000000"


class _NullProviderBundleFactory:
    """T030's retry endpoint resolves providers eagerly for the background
    task even though this test's task never gets far enough to use them (the
    test's `db_session` is never committed, so a separately-connected
    background task can't see the row it would act on) — so a placeholder is
    enough here."""

    def __call__(self) -> object:
        return object()

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def workspace_api(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    # Clear any workspace auto-created by other tests via the shared session so
    # each workspace test starts from an empty corpus (first = active).
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.flush()

    # The retry endpoint's `BackgroundTasks.add_task` really executes after
    # the response is sent (this fixture drives the app through a real ASGI
    # transport, not a stubbed one). Left unpatched, `dispatch_pending_rebuild`
    # would open a real connection through `decision_assistant.db`'s
    # process-wide engine on *this test's* event loop; since that loop is
    # torn down when the test ends, a later, differently-looped test that
    # reuses a pooled connection from the same engine singleton fails with
    # "attached to a different loop" (observed against
    # `test_public_business_routes_use_v1_namespace`). The row is invisible
    # to that background task anyway — `db_session` here is never committed,
    # so a separately-connected session can't see it — so the real call does
    # no useful work, only leaves the poisoned connection behind.
    async def _noop_dispatch_pending_rebuild(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "decision_assistant.workspace.router.dispatch_pending_rebuild",
        _noop_dispatch_pending_rebuild,
    )
    owner = User(
        username=f"workspace-owner-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    db_session.add(owner)
    await db_session.flush()

    app = create_app()
    app.state.provider_bundle_factory = _NullProviderBundleFactory()

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


async def test_get_corpus_rebuild_404_when_none_ever_ran(
    workspace_api: httpx.AsyncClient,
) -> None:
    workspace = await _create(workspace_api, "Atlas")

    response = await workspace_api.get(
        f"/api/v1/workspaces/{workspace['id']}/corpus-rebuild"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "corpus_rebuild_not_found"


async def test_get_corpus_rebuild_returns_latest_status(
    workspace_api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    workspace = await _create(workspace_api, "Atlas")
    db_session.add(
        CorpusRebuild(
            workspace_id=UUID(workspace["id"]),
            status="failed",
            reason="corpus_reset_required",
            documents_total=2,
            documents_completed=1,
            error={"code": "ingestion_failed", "document_id": str(uuid4())},
        )
    )
    await db_session.flush()

    response = await workspace_api.get(
        f"/api/v1/workspaces/{workspace['id']}/corpus-rebuild"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["documents_total"] == 2
    assert body["documents_completed"] == 1
    assert body["error"]["code"] == "ingestion_failed"


async def test_retry_corpus_rebuild_404_when_none_ever_ran(
    workspace_api: httpx.AsyncClient,
) -> None:
    workspace = await _create(workspace_api, "Atlas")

    response = await workspace_api.post(
        f"/api/v1/workspaces/{workspace['id']}/corpus-rebuild/retry"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "corpus_rebuild_not_found"


@pytest.mark.parametrize("blocking_status", ["pending", "running", "completed"])
async def test_retry_corpus_rebuild_409_when_not_failed(
    workspace_api: httpx.AsyncClient,
    db_session: AsyncSession,
    blocking_status: str,
) -> None:
    workspace = await _create(workspace_api, "Atlas")
    db_session.add(
        CorpusRebuild(
            workspace_id=UUID(workspace["id"]),
            status=blocking_status,
            reason="corpus_reset_required",
            documents_total=1,
            documents_completed=0,
        )
    )
    await db_session.flush()

    response = await workspace_api.post(
        f"/api/v1/workspaces/{workspace['id']}/corpus-rebuild/retry"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "corpus_rebuild_not_retryable"


async def test_retry_corpus_rebuild_creates_pending_row_when_latest_failed(
    workspace_api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    workspace = await _create(workspace_api, "Atlas")
    db_session.add(
        CorpusRebuild(
            workspace_id=UUID(workspace["id"]),
            status="failed",
            reason="corpus_reset_required",
            documents_total=1,
            documents_completed=0,
            error={"code": "ingestion_failed"},
            # `created_at`'s `server_default=func.now()` is transaction-scoped
            # (`CURRENT_TIMESTAMP`), identical across every insert in this
            # test's single open transaction; without an explicit, earlier
            # value here the "latest rebuild" ordering below is a tie between
            # this row and the one `retry` creates.
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    await db_session.flush()

    response = await workspace_api.post(
        f"/api/v1/workspaces/{workspace['id']}/corpus-rebuild/retry"
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["reason"] == "manual_retry"

    follow_up = await workspace_api.get(
        f"/api/v1/workspaces/{workspace['id']}/corpus-rebuild"
    )
    assert follow_up.json()["status"] == "pending"
    assert follow_up.json()["reason"] == "manual_retry"


async def test_retry_route_takes_the_process_wide_lock(
    workspace_api: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB72(a): the retry route inserts a `pending` rebuild, so it needs the switch lock too.

    Without the lock a manual retry here and a confirmed switch on another workspace can both
    pass: the switch's `active_rebuild_workspace_ids` read does not see this still-unwritten
    rebuild. Deleting the call from `workspace/router.py` must fail this test.
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

    workspace = await _create(workspace_api, "Atlas")
    db_session.add(
        CorpusRebuild(
            workspace_id=UUID(workspace["id"]),
            status="failed",
            reason="corpus_reset_required",
            documents_total=1,
            documents_completed=0,
            error={"code": "ingestion_failed"},
            # Same transaction-timestamp tie as the test above: the retry inserts a row whose
            # `created_at` default is this transaction's `CURRENT_TIMESTAMP`.
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    await db_session.flush()

    response = await workspace_api.post(
        f"/api/v1/workspaces/{workspace['id']}/corpus-rebuild/retry"
    )

    assert response.status_code == 202
    assert locked == [db_session], (
        "the retry route did not take the process-wide provider-switch lock before inserting its "
        "`pending` rebuild, so a retry can interleave with a confirmed provider switch (DB72)"
    )
