import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class PasswordManager:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, value: str) -> str:
        return self._hasher.hash(value)

    def verify(self, stored_hash: str, value: str) -> bool:
        try:
            return self._hasher.verify(stored_hash, value)
        except (InvalidHashError, VerificationError):
            return False

    def generate_recovery_code(self) -> str:
        return secrets.token_urlsafe(24)
