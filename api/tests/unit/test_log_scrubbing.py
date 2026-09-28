import base64
import io
import logging
from collections.abc import Callable
from pathlib import Path

from pydantic import SecretStr

from decision_assistant.config import Settings
from decision_assistant.diagnostics.logging import (
    LOG_FILE_NAME,
    REDACTED,
    SecretScrubbingFilter,
    SecretScrubbingFormatter,
    configure_logging,
    scrub_secrets,
    scrub_values,
    secret_values,
)

_GEMINI_KEY = "fake-gemini-key-2f9c1a"
_JWT_SECRET = "fake-jwt-secret-b41d7e"
_DB_PASSWORD = "fake-db-password-9de3"
_DATABASE_URL = f"postgresql+asyncpg://db_user:{_DB_PASSWORD}@db:5432/decision_assistant"

_TEST_LOGGER_NAME = "decision_assistant.tests.log_scrubbing"
#: The loggers `configure_logging` attaches its file handler to. `uvicorn.error` is deliberately
#: absent: it propagates to `uvicorn`, so a handler there as well would write every line twice
#: (DB61).
_ROOT_AND_UVICORN_LOGGERS = ("", "uvicorn", "uvicorn.access")


def _settings(**overrides: object) -> Settings:
    fields: dict[str, object] = {
        "gemini_api_key": SecretStr(_GEMINI_KEY),
        "auth_jwt_secret": SecretStr(_JWT_SECRET),
        "database_url": _DATABASE_URL,
    }
    fields.update(overrides)
    return Settings(**fields)


def _render(
    secrets: tuple[str, ...],
    emit: Callable[[logging.Logger], None],
    *,
    use_filter: bool = True,
    use_formatter: bool = True,
) -> str:
    """Run `emit` against a logger wired with only the pieces under test."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    if use_filter:
        handler.addFilter(SecretScrubbingFilter(secrets))
    if use_formatter:
        handler.setFormatter(SecretScrubbingFormatter("%(levelname)s %(message)s", secrets=secrets))
    logger = logging.getLogger(_TEST_LOGGER_NAME)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        emit(logger)
    finally:
        logger.removeHandler(handler)
    return stream.getvalue()


def _detach(handler: logging.Handler) -> None:
    for name in _ROOT_AND_UVICORN_LOGGERS:
        logging.getLogger(name).removeHandler(handler)
    handler.close()


def test_scrub_values_adds_encoded_and_userinfo_forms() -> None:
    # DB56: a library logs the connection string, not the raw password, so exact-value scrubbing
    # alone would miss the percent-encoded and userinfo shapes.
    settings = _settings(ollama_base_url="http://ollama:s3cret-pw@ollama:11434")
    values = scrub_values(settings)

    assert _GEMINI_KEY in values
    assert base64.b64encode(_GEMINI_KEY.encode()).decode("ascii") in values
    assert "s3cret-pw" in values
    assert "ollama:s3cret-pw" in values
    # The username is not a secret; redacting it would only make logs harder to read.
    assert "ollama" not in values


def test_scrub_secrets_redacts_a_percent_encoded_password() -> None:
    settings = _settings(
        database_url="postgresql+asyncpg://db_user:p%40ss%2Fword@db:5432/decision_assistant"
    )

    scrubbed = scrub_secrets(
        "connect postgresql://db_user:p%40ss%2Fword@db", scrub_values(settings)
    )

    assert "p%40ss%2Fword" not in scrubbed
    assert "p@ss/word" not in scrubbed
    assert REDACTED in scrubbed


def test_configure_logging_writes_each_record_once(tmp_path: Path) -> None:
    # DB61: `uvicorn.error` has no handler of its own and propagates to `uvicorn`, so attaching the
    # file handler to both wrote every startup line and traceback twice.
    settings = _settings(log_directory=tmp_path)
    handler = configure_logging(settings)
    try:
        logging.getLogger("uvicorn.error").warning("startup line once")
        logging.getLogger("uvicorn.access").warning("access line once")
        logging.getLogger("decision_assistant.main").warning("app line once")
        handler.flush()
    finally:
        _detach(handler)

    content = (tmp_path / LOG_FILE_NAME).read_text()
    assert content.count("startup line once") == 1
    assert content.count("access line once") == 1
    assert content.count("app line once") == 1


def test_secret_values_includes_every_configured_secret() -> None:
    assert set(secret_values(_settings())) == {
        _GEMINI_KEY,
        _JWT_SECRET,
        _DB_PASSWORD,
    }


def test_secret_values_drops_empty_duplicates_and_orders_longest_first() -> None:
    short = "shared-secret-value"
    values = secret_values(
        _settings(
            gemini_api_key=SecretStr(short),
            auth_jwt_secret=SecretStr(f"{short}-and-more"),
            database_url="postgresql+asyncpg://db_user:@db:5432/decision_assistant",
        )
    )

    # Newest-first replacement order matters: a secret containing another one must be replaced
    # whole, or the longer value's tail survives as a fragment.
    assert values == (f"{short}-and-more", short)
    assert _DB_PASSWORD not in values


def test_secret_values_ignores_an_unparsable_database_url() -> None:
    # A malformed DATABASE_URL is a startup-config concern (validate_startup_config's job); it
    # must not stop logging from being configured.
    values = secret_values(_settings(database_url="not a url"))

    assert set(values) == {_GEMINI_KEY, _JWT_SECRET}


def test_filter_redacts_secrets_from_message_and_args_without_the_formatter() -> None:
    secrets = secret_values(_settings())

    def emit(logger: logging.Logger) -> None:
        logger.info("provider key=%s", _GEMINI_KEY)
        logger.info("jwt=%s db=%s", _JWT_SECRET, _DATABASE_URL)
        logger.info("plain line survives")

    output = _render(secrets, emit, use_formatter=False)

    for secret in (_GEMINI_KEY, _JWT_SECRET, _DB_PASSWORD):
        assert secret not in output
    assert output.count(REDACTED) == 3
    # The rest of the line is left intact — scrubbing replaces values, it does not drop messages.
    assert "provider key=" in output
    assert "db_user" in output
    assert "db:5432" in output
    assert "plain line survives" in output


def test_filter_redacts_secret_in_dict_args() -> None:
    secrets = secret_values(_settings())
    output = _render(
        secrets,
        lambda logger: logger.info("key=%(key)s", {"key": _GEMINI_KEY}),
        use_formatter=False,
    )

    assert _GEMINI_KEY not in output
    assert REDACTED in output


def test_formatter_redacts_secret_in_an_exception_traceback_without_the_filter() -> None:
    # The filter cannot see a traceback: it is rendered from `exc_info` by the formatter, so a
    # secret inside the exception's own message is only reachable here (and `formatMessage`
    # deliberately leaves the logger name alone).
    secrets = secret_values(_settings())

    def emit(logger: logging.Logger) -> None:
        try:
            raise ValueError(f"provider rejected key {_GEMINI_KEY}")
        except ValueError:
            logger.exception("generation failed")

    output = _render(secrets, emit, use_filter=False)

    assert _GEMINI_KEY not in output
    assert REDACTED in output
    assert "generation failed" in output
    assert "ValueError" in output


def test_scrub_secrets_has_no_minimum_length_rule() -> None:
    # A short secret is still a secret; a "looks too short to be a secret" heuristic is a leak.
    assert scrub_secrets("value=abc", ("abc",)) == f"value={REDACTED}"
    assert scrub_secrets("nothing to do", ()) == "nothing to do"
    assert scrub_secrets("nothing to do", ("",)) == "nothing to do"


def test_configure_logging_writes_a_rotating_scrubbed_file(tmp_path: Path) -> None:
    settings = _settings(log_directory=tmp_path, log_max_bytes=200, log_backup_count=2)
    handler = configure_logging(settings)
    try:
        logger = logging.getLogger("decision_assistant.tests.log_scrubbing.rotation")
        for index in range(20):
            logger.warning("rotation line %d key=%s padded=%s", index, _GEMINI_KEY, "x" * 60)
        handler.flush()
    finally:
        _detach(handler)

    assert (tmp_path / LOG_FILE_NAME).exists()
    # Rotation actually happened, not just a single growing file.
    assert (tmp_path / f"{LOG_FILE_NAME}.1").exists()
    for path in tmp_path.iterdir():
        content = path.read_text()
        assert _GEMINI_KEY not in content
        assert _JWT_SECRET not in content
        assert _DB_PASSWORD not in content


def test_configure_logging_replaces_its_own_handlers_on_a_second_call(tmp_path: Path) -> None:
    settings = _settings(log_directory=tmp_path, log_max_bytes=200, log_backup_count=1)
    first = configure_logging(settings)
    second = configure_logging(settings)
    try:
        for name in _ROOT_AND_UVICORN_LOGGERS:
            marked = [
                handler
                for handler in logging.getLogger(name).handlers
                if getattr(handler, "_decision_assistant_file_handler", False)
            ]
            assert marked == [second], name
        # The superseded handler is closed, not merely detached — a duplicate would write every
        # line twice and hold a second open file descriptor to the same log.
        assert first not in logging.getLogger().handlers
    finally:
        _detach(second)
