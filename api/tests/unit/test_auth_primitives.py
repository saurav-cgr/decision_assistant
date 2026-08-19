from uuid import uuid4

from decision_assistant.auth.passwords import PasswordManager
from decision_assistant.auth.tokens import AccessTokenService
from decision_assistant.config import Settings
from decision_assistant.models import User


def test_password_manager_hashes_and_verifies_passwords() -> None:
    manager = PasswordManager()
    stored_hash = manager.hash("correct horse battery staple")

    assert stored_hash != "correct horse battery staple"
    assert manager.verify(stored_hash, "correct horse battery staple")
    assert not manager.verify(stored_hash, "wrong password")


def test_access_token_is_bound_to_user_and_token_version() -> None:
    user = User(
        id=uuid4(),
        username="token-user",
        password_hash="unused",
        recovery_code_id=uuid4(),
        recovery_code_hash="unused",
        token_version=3,
    )
    service = AccessTokenService(
        Settings(auth_jwt_secret="test-signing-secret-for-token-tests")
    )

    claims = service.decode(service.issue(user))

    assert claims is not None
    assert claims.user_id == user.id
    assert claims.token_version == 3


def test_access_token_rejects_tampered_payload() -> None:
    service = AccessTokenService(
        Settings(auth_jwt_secret="test-signing-secret-for-token-tests")
    )

    assert service.decode("not.a.valid.token") is None
