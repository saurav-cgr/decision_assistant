from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.passwords import PasswordManager
from decision_assistant.auth.tokens import AccessTokenService
from decision_assistant.errors import ApplicationError
from decision_assistant.models import User


class InvalidCredentials(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_credentials",
            message="Invalid username, password, or recovery code",
            status_code=401,
        )


class UsernameConflict(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="username_conflict",
            message="That username is already in use",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    user: User
    access_token: str
    recovery_code: str | None = None


class AuthenticationService:
    def __init__(
        self,
        session: AsyncSession,
        password_manager: PasswordManager,
        token_service: AccessTokenService,
    ) -> None:
        self._session = session
        self._password_manager = password_manager
        self._token_service = token_service

    async def sign_up(self, *, username: str, password: str) -> AuthenticationResult:
        existing = await self._session.scalar(
            select(User.id).where(User.username == username)
        )
        if existing is not None:
            raise UsernameConflict()
        user, recovery_code = self._new_user(username=username, password=password)
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise UsernameConflict() from exc
        return AuthenticationResult(
            user=user,
            access_token=self._token_service.issue(user),
            recovery_code=recovery_code,
        )

    async def login(self, *, username: str, password: str) -> AuthenticationResult:
        user = await self._session.scalar(select(User).where(User.username == username))
        if user is None or not self._password_manager.verify(user.password_hash, password):
            raise InvalidCredentials()
        return AuthenticationResult(user=user, access_token=self._token_service.issue(user))

    async def recover_username(self, *, recovery_code: str) -> str:
        recovery_code_id = _recovery_code_id(recovery_code)
        if recovery_code_id is None:
            raise InvalidCredentials()
        user = await self._session.scalar(
            select(User).where(User.recovery_code_id == recovery_code_id)
        )
        if user is None or not self._password_manager.verify(
            user.recovery_code_hash, recovery_code
        ):
            raise InvalidCredentials()
        return user.username

    async def reset_password(
        self,
        *,
        username: str,
        password: str,
        recovery_code: str,
    ) -> AuthenticationResult:
        user = await self._session.scalar(select(User).where(User.username == username))
        if user is None or not self._password_manager.verify(
            user.recovery_code_hash, recovery_code
        ):
            raise InvalidCredentials()
        user.password_hash = self._password_manager.hash(password)
        recovery_code = self._rotate_recovery_code(user)
        user.token_version += 1
        await self._session.flush()
        return AuthenticationResult(user=user, access_token="", recovery_code=recovery_code)

    async def change_password(
        self,
        *,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        self._require_password(user, current_password)
        user.password_hash = self._password_manager.hash(new_password)
        user.token_version += 1
        await self._session.flush()

    async def change_username(
        self,
        *,
        user: User,
        current_password: str,
        username: str,
    ) -> None:
        self._require_password(user, current_password)
        duplicate = await self._session.scalar(
            select(User.id).where(User.username == username, User.id != user.id)
        )
        if duplicate is not None:
            raise UsernameConflict()
        user.username = username
        user.token_version += 1
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise UsernameConflict() from exc

    async def rotate_recovery_code(
        self,
        *,
        user: User,
        current_password: str,
    ) -> str:
        self._require_password(user, current_password)
        recovery_code = self._rotate_recovery_code(user)
        await self._session.flush()
        return recovery_code

    async def logout(self, user: User) -> None:
        user.token_version += 1
        await self._session.flush()

    def _new_user(self, *, username: str, password: str) -> tuple[User, str]:
        recovery_code_id = uuid4()
        recovery_code = _new_recovery_code(recovery_code_id, self._password_manager)
        return (
            User(
                username=username,
                password_hash=self._password_manager.hash(password),
                recovery_code_id=recovery_code_id,
                recovery_code_hash=self._password_manager.hash(recovery_code),
            ),
            recovery_code,
        )

    def _rotate_recovery_code(self, user: User) -> str:
        recovery_code_id = uuid4()
        recovery_code = _new_recovery_code(recovery_code_id, self._password_manager)
        user.recovery_code_id = recovery_code_id
        user.recovery_code_hash = self._password_manager.hash(recovery_code)
        return recovery_code

    def _require_password(self, user: User, password: str) -> None:
        if not self._password_manager.verify(user.password_hash, password):
            raise InvalidCredentials()


def _new_recovery_code(recovery_code_id: UUID, manager: PasswordManager) -> str:
    return f"{recovery_code_id}.{manager.generate_recovery_code()}"


def _recovery_code_id(recovery_code: str) -> UUID | None:
    prefix, separator, _ = recovery_code.partition(".")
    if not separator:
        return None
    try:
        return UUID(prefix)
    except ValueError:
        return None
