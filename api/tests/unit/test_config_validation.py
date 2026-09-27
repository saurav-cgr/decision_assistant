import pytest
from pydantic import SecretStr

from decision_assistant.config import ConfigurationError, Settings, validate_startup_config

_REAL_DATABASE_URL = "postgresql+asyncpg://real_user:real_password@db:5432/decision_assistant"


def _valid_settings(**overrides: object) -> Settings:
    fields: dict[str, object] = {
        "gemini_api_key": None,
        "auth_jwt_secret": SecretStr("a-real-random-secret"),
        "database_url": _REAL_DATABASE_URL,
    }
    fields.update(overrides)
    return Settings(**fields)


def test_validate_startup_config_accepts_real_secret_and_database_url() -> None:
    validate_startup_config(_valid_settings())


def test_validate_startup_config_rejects_missing_auth_jwt_secret() -> None:
    settings = _valid_settings(auth_jwt_secret=None)

    try:
        validate_startup_config(settings)
    except ConfigurationError as exc:
        assert "AUTH_JWT_SECRET" in str(exc)
    else:
        raise AssertionError("expected ConfigurationError for missing AUTH_JWT_SECRET")


def test_validate_startup_config_rejects_blank_auth_jwt_secret() -> None:
    settings = _valid_settings(auth_jwt_secret=SecretStr("   "))

    try:
        validate_startup_config(settings)
    except ConfigurationError as exc:
        assert "AUTH_JWT_SECRET" in str(exc)
    else:
        raise AssertionError("expected ConfigurationError for blank AUTH_JWT_SECRET")


def test_validate_startup_config_rejects_placeholder_database_url() -> None:
    settings = _valid_settings(
        database_url=(
            "postgresql+asyncpg://decision_assistant:decision_assistant"
            "@db:5432/decision_assistant"
        )
    )

    try:
        validate_startup_config(settings)
    except ConfigurationError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("expected ConfigurationError for placeholder DATABASE_URL")


# checker V76(b): the shared credential must be caught regardless of how the
# rest of the connection string is spelled, not just the one exact literal.
@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://decision_assistant:decision_assistant@db/decision_assistant",
        "postgresql+asyncpg://decision_assistant:decision_assistant@db:5432/decision_assistant?ssl=disable",
        "postgresql+asyncpg://decision_assistant:decision_assistant@some-other-host:5433/another_db",
    ],
)
def test_validate_startup_config_rejects_placeholder_credential_under_any_spelling(
    database_url: str,
) -> None:
    settings = _valid_settings(database_url=database_url)

    try:
        validate_startup_config(settings)
    except ConfigurationError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError(
            f"expected ConfigurationError for shared-credential URL: {database_url}"
        )


def test_validate_startup_config_accepts_non_placeholder_credential_on_same_host() -> None:
    # Same host/port/db name as the placeholder, different credential — must
    # not false-positive on host/db-name alone.
    settings = _valid_settings(
        database_url="postgresql+asyncpg://real_user:real_password@db:5432/decision_assistant"
    )

    validate_startup_config(settings)


# --- T039 (US5): the startup contract after the env bootstrap was removed -------------------------
#
# T039's wording asks for `Settings` *construction* to raise. The project deliberately validates in
# `lifespan` instead (T013/DB17/M-018) so the existing suite can build a bare `Settings()` for
# behaviour unrelated to auth — the human confirmed that reading on 2026-09-26, so the behaviour
# these tests pin is `validate_startup_config`, which is what `lifespan` calls before any DB access.


def test_no_auth_bootstrap_settings_exist_any_more() -> None:
    # T042 removed `AUTH_BOOTSTRAP_USERNAME`/`AUTH_BOOTSTRAP_PASSWORD`. `Settings` ignores unknown
    # kwargs, so a re-added stale `.env` entry or a resurrected keyword would be swallowed silently
    # — this asserts the fields are gone rather than merely unused.
    settings = _valid_settings()

    assert not hasattr(settings, "auth_bootstrap_username")
    assert not hasattr(settings, "auth_bootstrap_password")


def test_startup_accepts_a_configuration_shaped_like_make_setup_output() -> None:
    # The secrets `make setup` writes are 64-char hex (see setup/bootstrap.py) and there are no
    # bootstrap credentials to supply — the pair is exactly what a freshly set-up install has, and
    # it must start.
    from decision_assistant.setup.bootstrap import generate_first_run_secrets

    generated = generate_first_run_secrets()
    settings = _valid_settings(
        auth_jwt_secret=SecretStr(generated.auth_jwt_secret),
        database_url=(
            "postgresql+asyncpg://decision_assistant:"
            f"{generated.database_password}@db:5432/decision_assistant"
        ),
    )

    validate_startup_config(settings)


def test_startup_rejects_a_generated_password_that_is_still_the_placeholder() -> None:
    # The failure mode this guards: `make setup` writes a real `AUTH_JWT_SECRET` but the operator
    # hand-edits `.env` back to the shared placeholder password. A real JWT secret must not be
    # enough to get the app running on the shared database credential (DB8/DB26).
    settings = _valid_settings(
        database_url=(
            "postgresql+asyncpg://decision_assistant:decision_assistant@db:5432/decision_assistant"
        )
    )

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        validate_startup_config(settings)
