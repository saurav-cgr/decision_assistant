"""First-run setup: create the single local user (US5/FR-014, T042).

This replaces the `AUTH_BOOTSTRAP_USERNAME`/`AUTH_BOOTSTRAP_PASSWORD` environment bootstrap. Those
were two more shared-default values in `.env` and a second, parallel way to define "the" user; a
fresh install now serves requests with no user at all, `GET /setup/status` says so, and
`POST /setup/password` creates the user once with a password the operator chooses.

`main.py` deliberately no longer creates a user during startup: doing so would mean the app decides
a credential, which is exactly what US5 exists to remove.
"""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.models import User
from decision_assistant.auth.passwords import PasswordManager
from decision_assistant.auth.service import AuthenticationResult
from decision_assistant.auth.tokens import AccessTokenService
from decision_assistant.errors import ApplicationError
from decision_assistant.workspace.models import Workspace

#: The only username this product creates. There is one local user, so a first-run screen asking the
#: operator to invent a username would be asking a question with a single sensible answer; the name
#: is fixed here instead of being configured.
SETUP_USERNAME = "decision_assistant"

_SETUP_LOCK_SQL = "SELECT pg_advisory_xact_lock(582029)"


@dataclass(frozen=True, slots=True)
class SetupStatus:
    needs_password_setup: bool
    needs_provider_disclosure: bool


class PasswordAlreadySetUp(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="password_already_set_up",
            message="A password has already been set up for this install",
            status_code=409,
            retryable=False,
        )


class SetupService:
    def __init__(
        self,
        session: AsyncSession,
        password_manager: PasswordManager,
        token_service: AccessTokenService,
    ) -> None:
        self._session = session
        self._password_manager = password_manager
        self._token_service = token_service

    async def status(self) -> SetupStatus:
        """What a browser still has to be asked before the app is usable.

        Both halves are install-wide rather than per workspace, because the first-run screens appear
        before any workspace exists: `needs_password_setup` is "there is no user at all", and
        `needs_provider_disclosure` is "no workspace has acknowledged the disclosure yet".
        """
        user_exists = await self._session.scalar(select(User.id).limit(1)) is not None
        acknowledged = await self._session.scalar(
            select(Workspace.id).where(Workspace.disclosure_acknowledged_at.is_not(None)).limit(1)
        )
        return SetupStatus(
            needs_password_setup=not user_exists,
            needs_provider_disclosure=acknowledged is None,
        )

    async def create_password(self, *, password: str) -> AuthenticationResult:
        """Create the local user and sign them in.

        The advisory lock is the one the old env bootstrap used, so two concurrent first-run
        submissions serialize: the second sees the first one's user and gets 409 instead of creating
        a second account (nothing in the schema constrains "there is only one user").
        """
        await self._session.execute(text(_SETUP_LOCK_SQL))
        if await self._session.scalar(select(User.id).limit(1)) is not None:
            raise PasswordAlreadySetUp()

        recovery_code = self._password_manager.generate_recovery_code()
        user = User(
            username=SETUP_USERNAME,
            password_hash=self._password_manager.hash(password),
            recovery_code_id=uuid4(),
            recovery_code_hash=self._password_manager.hash(recovery_code),
        )
        self._session.add(user)
        await self._session.flush()

        # Workspaces that predate this password (created by an earlier env bootstrap, or left
        # unowned by a restored backup) are adopted, so setting a password cannot lock the operator
        # out of data that is already in the database.
        await self._session.execute(
            update(Workspace).where(Workspace.owner_user_id.is_(None)).values(owner_user_id=user.id)
        )
        return AuthenticationResult(
            user=user,
            access_token=self._token_service.issue(user),
            recovery_code=recovery_code,
        )
