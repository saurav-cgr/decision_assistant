"""T058 (US7/FR-018): `GET /diagnostics/bundle` — a downloadable, secret-free support archive.

The unit tests for the archive's contents live in `tests/unit/test_diagnostics_bundle.py`; these
tests cover the HTTP surface: authentication, the download headers, and that the response the
operator actually receives is a readable zip with no configured secret in it. The bundle reads the
real database revision, so this file exercises that read end to end rather than stubbing it.
"""

import io
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.auth.models import User
from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.main import create_app
from decision_assistant.version import get_app_version

GEMINI_KEY = "fake-gemini-key-diagnostics"
JWT_SECRET = "fake-jwt-secret-diagnostics"


def _settings(tmp_path: Path) -> Settings:
    # `database_url` is deliberately left to the environment: the route reads the database's real
    # migration revision, so this test needs the same database the rest of the suite uses.
    return Settings(
        upload_directory=tmp_path / "uploads",
        gemini_api_key=SecretStr(GEMINI_KEY),
        auth_jwt_secret=SecretStr(JWT_SECRET),
    )


def _client(
    session: AsyncSession,
    settings: Settings,
    user: User | None,
) -> httpx.AsyncClient:
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


async def _user(session: AsyncSession) -> User:
    user = User(
        username="diagnostics-user",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    session.add(user)
    await session.flush()
    return user


async def test_bundle_requires_authentication(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)

    async with _client(db_session, settings, user=None) as client:
        response = await client.get("/api/v1/diagnostics/bundle")

    assert response.status_code == 401
    assert "zip" not in response.headers.get("content-type", "")


async def test_bundle_download_is_a_scrubbed_zip_with_download_headers(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    user = await _user(db_session)

    async with _client(db_session, settings, user=user) as client:
        response = await client.get("/api/v1/diagnostics/bundle")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "decision-assistant-diagnostics-" in disposition
    assert disposition.endswith('.zip"')

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        members = set(archive.namelist())
        assert {"version.txt", "alembic-current.txt", "settings.json"} <= members
        assert archive.read("version.txt").decode().strip() == get_app_version()
        # The revision came from the real database, not a placeholder.
        assert archive.read("alembic-current.txt").decode().strip()

    database_password = make_url(settings.database_url).password
    assert database_password
    for secret in (GEMINI_KEY, JWT_SECRET, database_password):
        assert secret.encode() not in response.content
