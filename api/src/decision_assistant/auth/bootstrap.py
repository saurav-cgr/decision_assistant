from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.passwords import PasswordManager
from decision_assistant.models import User, Workspace


@dataclass(frozen=True, slots=True)
class BootstrapCredentials:
    username: str
    password: str


class BootstrapService:
    def __init__(self, session: AsyncSession, password_manager: PasswordManager) -> None:
        self._session = session
        self._password_manager = password_manager

    async def ensure_user(self, credentials: BootstrapCredentials) -> User:
        await self._session.execute(text("SELECT pg_advisory_xact_lock(582029)"))
        user = await self._session.scalar(
            select(User).where(User.username == credentials.username)
        )
        if user is None:
            recovery_code = self._password_manager.generate_recovery_code()
            user = User(
                username=credentials.username,
                password_hash=self._password_manager.hash(credentials.password),
                recovery_code_id=uuid4(),
                recovery_code_hash=self._password_manager.hash(recovery_code),
            )
            self._session.add(user)
            await self._session.flush()

        await self._session.execute(
            update(Workspace)
            .where(Workspace.owner_user_id.is_(None))
            .values(owner_user_id=user.id)
        )
        return user
