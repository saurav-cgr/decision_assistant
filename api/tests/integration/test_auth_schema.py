from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _insert_user(db_session: AsyncSession, username: str) -> UUID:
    user_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users "
            "(id, username, password_hash, recovery_code_id, recovery_code_hash) "
            "VALUES (:id, :username, :password_hash, :recovery_code_id, "
            ":recovery_code_hash)"
        ),
        {
            "id": user_id,
            "username": username,
            "password_hash": "not-a-real-password-hash",
            "recovery_code_id": uuid4(),
            "recovery_code_hash": "not-a-real-recovery-code-hash",
        },
    )
    return user_id


@pytest.mark.asyncio
async def test_workspace_names_and_active_selection_are_owner_scoped(
    db_session: AsyncSession,
) -> None:
    first_owner_id = await _insert_user(db_session, "first-owner")
    second_owner_id = await _insert_user(db_session, "second-owner")

    for owner_id in (first_owner_id, second_owner_id):
        await db_session.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, is_active) "
                "VALUES (:id, :owner_user_id, :name, true)"
            ),
            {
                "id": uuid4(),
                "owner_user_id": owner_id,
                "name": "Shared project name",
            },
        )

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO workspaces (id, owner_user_id, name, is_active) "
                    "VALUES (:id, :owner_user_id, :name, false)"
                ),
                {
                    "id": uuid4(),
                    "owner_user_id": first_owner_id,
                    "name": "Shared project name",
                },
            )

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO workspaces (id, owner_user_id, name, is_active) "
                    "VALUES (:id, :owner_user_id, :name, true)"
                ),
                {
                    "id": uuid4(),
                    "owner_user_id": first_owner_id,
                    "name": "Another workspace",
                },
            )
