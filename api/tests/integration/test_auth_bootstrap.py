from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.bootstrap import BootstrapCredentials, BootstrapService
from decision_assistant.auth.passwords import PasswordManager


@pytest.mark.asyncio
async def test_bootstrap_user_claims_legacy_workspaces_once(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
        {"id": uuid4(), "name": "Legacy workspace"},
    )
    service = BootstrapService(db_session, PasswordManager())

    user = await service.ensure_user(
        BootstrapCredentials(username="bootstrap-user", password="bootstrap-password")
    )
    repeated = await service.ensure_user(
        BootstrapCredentials(username="bootstrap-user", password="bootstrap-password")
    )

    owner_id = await db_session.scalar(
        text("SELECT owner_user_id FROM workspaces WHERE name = :name"),
        {"name": "Legacy workspace"},
    )
    users = await db_session.scalar(text("SELECT count(*) FROM users"))
    assert owner_id == user.id
    assert repeated.id == user.id
    assert users == 1
