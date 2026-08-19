from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.service import InvalidCredentials
from decision_assistant.auth.tokens import AccessTokenService
from decision_assistant.db import get_session
from decision_assistant.models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None:
        raise InvalidCredentials()
    claims = AccessTokenService(request.app.state.settings).decode(
        credentials.credentials
    )
    if claims is None:
        raise InvalidCredentials()
    user = await session.get(User, claims.user_id)
    if user is None or user.token_version != claims.token_version:
        raise InvalidCredentials()
    return user
