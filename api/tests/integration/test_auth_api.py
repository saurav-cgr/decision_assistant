from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.main import create_app


@pytest_asyncio.fixture
async def auth_api(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(auth_jwt_secret="test-signing-secret-for-auth-api-tests")
    )

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def _sign_up(client: httpx.AsyncClient, username: str = "new-user") -> dict:
    response = await client.post(
        "/api/v1/auth/signup",
        json={"username": username, "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return response.json()


async def test_signup_issues_access_token_and_one_time_recovery_code(
    auth_api: httpx.AsyncClient,
) -> None:
    body = await _sign_up(auth_api)

    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "new-user"
    assert body["recovery_code"]
    me = await auth_api.get(
        "/api/v1/auth/me",
        headers={"authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == "new-user"


async def test_signup_accepts_an_eight_character_password(
    auth_api: httpx.AsyncClient,
) -> None:
    response = await auth_api.post(
        "/api/v1/auth/signup",
        json={"username": "eight-character-password", "password": "password"},
    )

    assert response.status_code == 201


async def test_recovery_code_recovers_username_and_rotates_after_reset(
    auth_api: httpx.AsyncClient,
) -> None:
    signed_up = await _sign_up(auth_api)
    original_code = signed_up["recovery_code"]

    recovery = await auth_api.post(
        "/api/v1/auth/recover-username",
        json={"recovery_code": original_code},
    )
    assert recovery.status_code == 200
    assert recovery.json() == {"username": "new-user"}

    reset = await auth_api.post(
        "/api/v1/auth/reset-password",
        json={
            "username": "new-user",
            "password": "a different correct horse battery staple",
            "recovery_code": original_code,
        },
    )
    assert reset.status_code == 200
    assert reset.json()["recovery_code"] != original_code

    old_code = await auth_api.post(
        "/api/v1/auth/recover-username",
        json={"recovery_code": original_code},
    )
    assert old_code.status_code == 401
    assert old_code.json()["code"] == "invalid_credentials"


async def test_logout_invalidates_the_presented_access_token(
    auth_api: httpx.AsyncClient,
) -> None:
    signed_up = await _sign_up(auth_api)
    headers = {"authorization": f"Bearer {signed_up['access_token']}"}

    assert (await auth_api.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    assert (await auth_api.get("/api/v1/auth/me", headers=headers)).status_code == 401
