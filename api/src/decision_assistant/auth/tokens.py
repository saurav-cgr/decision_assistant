from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError

from decision_assistant.config import Settings
from decision_assistant.models import User

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "decision-assistant"


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    token_version: int


class AccessTokenService:
    def __init__(self, settings: Settings) -> None:
        secret = settings.auth_jwt_secret
        if secret is None or not secret.get_secret_value():
            raise ValueError("AUTH_JWT_SECRET must be configured")
        self._secret = secret.get_secret_value()
        self._ttl = timedelta(minutes=settings.auth_access_token_ttl_minutes)

    def issue(self, user: User) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user.id),
                "token_version": user.token_version,
                "iss": JWT_ISSUER,
                "iat": now,
                "exp": now + self._ttl,
            },
            self._secret,
            algorithm=JWT_ALGORITHM,
        )

    def decode(self, encoded_token: str) -> AccessTokenClaims | None:
        try:
            payload = jwt.decode(
                encoded_token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
            )
            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                token_version=int(payload["token_version"]),
            )
        except (InvalidTokenError, KeyError, TypeError, ValueError):
            return None
