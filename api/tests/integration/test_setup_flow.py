"""US5 first-run setup (T042/T043): the password flow replaces env bootstrap credentials.

These are cross-layer tests on purpose — the criterion is that a browser with no credentials can
*discover* that setup is needed and then complete it, so they drive the real HTTP routes with the
real `SetupService`, `PasswordManager` and token issuer, and read the database back.

The one thing they do not do is run `lifespan`: `create_app` alone is enough for these routes, and
running the real startup path would fire migrations, the pre-migration backup and the rebuild sweep
for a test about a password screen.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.bootstrap import SETUP_USERNAME, SetupService
from decision_assistant.auth.models import User
from decision_assistant.auth.passwords import PasswordManager
from decision_assistant.auth.tokens import AccessTokenService
from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.main import create_app
from decision_assistant.workspace.models import Workspace

PASSWORD = "a-first-run-password"
JWT_SECRET = "test-signing-secret-for-the-setup-flow"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        upload_directory=tmp_path,
        log_directory=tmp_path,
        auth_jwt_secret=SecretStr(JWT_SECRET),
    )


@pytest_asyncio.fixture
async def setup_client(
    db_session: AsyncSession, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    # "A fresh install" is a global property (there is no user at all), so the tests have to control
    # it rather than assume it: the shared test database is truncated once per session, but routes
    # commit, so an earlier test's user survives. Workspaces first — `owner_user_id` is
    # ON DELETE RESTRICT, so dropping users before their workspaces would fail.
    async def reset() -> None:
        await db_session.execute(delete(Workspace))
        await db_session.execute(delete(User))
        await db_session.commit()

    await reset()
    app = create_app(_settings(tmp_path))

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await reset()


async def _users(session: AsyncSession) -> list[User]:
    return list(await session.scalars(select(User)))


async def test_status_describes_a_fresh_install_without_any_credentials(
    setup_client: httpx.AsyncClient,
) -> None:
    response = await setup_client.get("/api/v1/setup/status")

    assert response.status_code == 200
    assert response.json() == {
        "needs_password_setup": True,
        "needs_provider_disclosure": True,
    }


async def test_creating_the_first_password_signs_the_user_in_and_closes_setup(
    setup_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    response = await setup_client.post(
        "/api/v1/setup/password", json={"password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["username"] == SETUP_USERNAME
    # The recovery code is returned exactly here; without it a forgotten password is unrecoverable.
    assert body["recovery_code"]

    assert (await setup_client.get("/api/v1/setup/status")).json() == {
        "needs_password_setup": False,
        "needs_provider_disclosure": True,
    }
    # The password is really usable, which is what the operator does next.
    login = await setup_client.post(
        "/api/v1/auth/login", json={"username": SETUP_USERNAME, "password": PASSWORD}
    )
    assert login.status_code == 200
    assert (await _users(db_session)) != []


async def test_a_second_setup_attempt_is_refused_and_creates_no_second_user(
    setup_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    first = await setup_client.post("/api/v1/setup/password", json={"password": PASSWORD})
    assert first.status_code == 200

    second = await setup_client.post(
        "/api/v1/setup/password", json={"password": "a-different-password"}
    )

    assert second.status_code == 409
    assert second.json()["code"] == "password_already_set_up"
    assert len(await _users(db_session)) == 1


async def test_a_short_password_is_rejected_before_any_user_exists(
    setup_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    response = await setup_client.post("/api/v1/setup/password", json={"password": "short"})

    assert response.status_code == 422
    assert await _users(db_session) == []


async def test_creating_the_password_adopts_workspaces_that_predate_it(
    setup_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # A restored backup, or a workspace created under the old env bootstrap, can have no owner.
    # Adopting it is what stops "set a password" from locking the operator out of existing data.
    legacy = Workspace(name="Legacy", owner_user_id=None)
    db_session.add(legacy)
    await db_session.flush()

    response = await setup_client.post("/api/v1/setup/password", json={"password": PASSWORD})

    assert response.status_code == 200
    user_id = response.json()["user"]["id"]
    await db_session.refresh(legacy)
    assert str(legacy.owner_user_id) == user_id


async def test_the_disclosure_flag_clears_once_a_workspace_acknowledges(
    setup_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    created = await setup_client.post("/api/v1/setup/password", json={"password": PASSWORD})
    assert created.status_code == 200

    from datetime import UTC, datetime

    workspace = Workspace(
        name="Acknowledged",
        owner_user_id=None,
        disclosure_acknowledged_at=datetime.now(UTC),
    )
    db_session.add(workspace)
    await db_session.commit()

    status = (await setup_client.get("/api/v1/setup/status")).json()
    assert status["needs_provider_disclosure"] is False


async def test_the_service_refuses_a_second_password_even_without_http(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The route is not the guard — the service is, so any future caller inherits it."""
    await db_session.execute(delete(Workspace))
    await db_session.execute(delete(User))
    await db_session.commit()

    service = SetupService(
        db_session,
        PasswordManager(),
        AccessTokenService(_settings(tmp_path)),
    )
    assert (await service.status()).needs_password_setup is True

    await service.create_password(password=PASSWORD)
    await db_session.commit()

    from decision_assistant.auth.bootstrap import PasswordAlreadySetUp

    with pytest.raises(PasswordAlreadySetUp):
        await service.create_password(password="another-password")

    await db_session.execute(delete(Workspace))
    await db_session.execute(delete(User))
    await db_session.commit()
