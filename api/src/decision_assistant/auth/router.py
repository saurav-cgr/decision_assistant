from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.auth.passwords import PasswordManager
from decision_assistant.auth.schemas import (
    AuthResponse,
    LoginRequest,
    PasswordChangeRequest,
    PasswordConfirmation,
    PasswordResetRequest,
    RecoveryCodeResponse,
    SignUpRequest,
    UsernameChangeRequest,
    UsernameRecoveryRequest,
    UsernameRecoveryResponse,
    UserResponse,
)
from decision_assistant.auth.service import AuthenticationResult, AuthenticationService
from decision_assistant.auth.tokens import AccessTokenService
from decision_assistant.db import get_session
from decision_assistant.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def get_authentication_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthenticationService:
    return AuthenticationService(
        session,
        PasswordManager(),
        AccessTokenService(request.app.state.settings),
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=str(user.id), username=user.username)


def _authentication_response(result: AuthenticationResult) -> AuthResponse:
    return AuthResponse(
        access_token=result.access_token,
        user=_user_response(result.user),
        recovery_code=result.recovery_code,
    )


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def sign_up(
    payload: SignUpRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AuthResponse:
    return _authentication_response(
        await service.sign_up(username=payload.username, password=payload.password)
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AuthResponse:
    return _authentication_response(
        await service.login(username=payload.username, password=payload.password)
    )


@router.post("/recover-username", response_model=UsernameRecoveryResponse)
async def recover_username(
    payload: UsernameRecoveryRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> UsernameRecoveryResponse:
    return UsernameRecoveryResponse(
        username=await service.recover_username(recovery_code=payload.recovery_code)
    )


@router.post("/reset-password", response_model=RecoveryCodeResponse)
async def reset_password(
    payload: PasswordResetRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> RecoveryCodeResponse:
    result = await service.reset_password(
        username=payload.username,
        password=payload.password,
        recovery_code=payload.recovery_code,
    )
    return RecoveryCodeResponse(recovery_code=result.recovery_code or "")


@router.get("/me", response_model=UserResponse)
async def current_user(
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return _user_response(user)


@router.post("/logout", status_code=204)
async def logout(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> None:
    await service.logout(user)


@router.patch("/me/password", status_code=204)
async def change_password(
    payload: PasswordChangeRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> None:
    await service.change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.patch("/me/username", status_code=204)
async def change_username(
    payload: UsernameChangeRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> None:
    await service.change_username(
        user=user,
        current_password=payload.current_password,
        username=payload.username,
    )


@router.post("/me/recovery-code", response_model=RecoveryCodeResponse)
async def rotate_recovery_code(
    payload: PasswordConfirmation,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> RecoveryCodeResponse:
    return RecoveryCodeResponse(
        recovery_code=await service.rotate_recovery_code(
            user=user,
            current_password=payload.current_password,
        )
    )
