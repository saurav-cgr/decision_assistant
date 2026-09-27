"""T040 (US5/FR-013): first-run secrets are unique per run and never logged.

Two halves, as the task asks. Uniqueness: the generator must not be able to hand two installs (or two
runs) the same value, and the value must be usable in all three places it goes — an `.env` line, a SQL
literal for `ALTER ROLE`, and a URL password. Secrecy: the setup step logs key *names* only, and the
gemini key is asserted absent from the produced log file so that the assertion fails if anyone ever
logs the whole update mapping.

The generator is exercised directly rather than through the shell script: `scripts/setup.sh` only
pipes text in and redirects stdout, so all the decision logic under test lives in this module
(see the module docstring for why the file itself is written on the host).
"""

import io
import logging
import re
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from decision_assistant.config import PLACEHOLDER_DB_CREDENTIALS, Settings
from decision_assistant.diagnostics.logging import LOG_FILE_NAME, configure_logging
from decision_assistant.setup.bootstrap import (
    ENV_KEYS,
    apply_first_run_setup,
    env_is_configured,
    generate_first_run_secrets,
    generate_secret,
    main,
    parse_env_text,
    render_database_url,
    update_env_text,
)

FAKE_GEMINI_KEY = "fake-gemini-key-for-setup-test"
HEX_SECRET = re.compile(r"\A[0-9a-f]{64}\Z")

EXAMPLE_ENV = """\
# Comment that must survive.
POSTGRES_DB=decision_assistant
POSTGRES_USER=decision_assistant
POSTGRES_PASSWORD=
DATABASE_URL=
GEMINI_API_KEY=
AUTH_JWT_SECRET=
"""

_LOG_TARGETS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    fields: dict[str, object] = {
        "log_directory": tmp_path,
        "gemini_api_key": SecretStr(FAKE_GEMINI_KEY),
    }
    fields.update(overrides)
    return Settings(**fields)


def _detach(handler: logging.Handler) -> None:
    """Undo `configure_logging` so this test's file handler cannot leak into later tests."""
    for name in _LOG_TARGETS:
        logging.getLogger(name).removeHandler(handler)
    handler.close()


def test_every_run_generates_distinct_secrets() -> None:
    drawn = [generate_first_run_secrets() for _ in range(200)]
    passwords = {item.database_password for item in drawn}
    jwt_secrets = {item.auth_jwt_secret for item in drawn}

    assert len(passwords) == len(drawn)
    assert len(jwt_secrets) == len(drawn)
    # The two fields of one draw must differ from each other too, or one leak would compromise both.
    assert all(item.database_password != item.auth_jwt_secret for item in drawn)


def test_generated_secrets_are_full_length_hex_and_never_the_placeholder() -> None:
    secrets_ = generate_first_run_secrets()

    assert HEX_SECRET.match(secrets_.database_password)
    assert HEX_SECRET.match(secrets_.auth_jwt_secret)
    # Hex, not opaque bytes: the same string goes into a URL password and a SQL literal unescaped, and
    # the `ALTER ROLE` step relies on that (a quote or backslash would need escaping in one or both).
    assert not set(secrets_.database_password) - set("0123456789abcdef")
    for value in (secrets_.database_password, secrets_.auth_jwt_secret):
        assert value not in PLACEHOLDER_DB_CREDENTIALS


def test_secret_generation_refuses_a_short_request() -> None:
    with pytest.raises(ValueError, match="shorter than 16 bytes"):
        generate_secret(nbytes=8)


def test_generated_password_survives_the_url_round_trip() -> None:
    password = generate_secret()
    url = render_database_url(
        {"DATABASE_URL": "postgresql+asyncpg://decision_assistant:@db:5432/decision_assistant"},
        password,
    )

    parsed = make_url(url)
    assert parsed.password == password
    assert parsed.host == "db"
    assert parsed.database == "decision_assistant"


def test_setup_fills_blank_values_and_preserves_comments_and_order() -> None:
    update, generated = apply_first_run_setup(EXAMPLE_ENV)

    values = parse_env_text(update.text)
    assert values["POSTGRES_PASSWORD"] == generated.database_password
    assert values["AUTH_JWT_SECRET"] == generated.auth_jwt_secret
    # DATABASE_URL was blank in the example, so it is derived from the POSTGRES_* names and carries
    # the new password — the app cannot connect to a database whose password is not in its URL.
    assert make_url(values["DATABASE_URL"]).password == generated.database_password
    assert "# Comment that must survive." in update.text
    assert update.text.index("POSTGRES_DB=") < update.text.index("AUTH_JWT_SECRET=")
    assert update.text.endswith("\n")
    assert set(update.applied) == set(ENV_KEYS)
    assert update.skipped == ()
    # A key it does not own is left exactly as it was, blank or not.
    assert values["GEMINI_API_KEY"] == ""


def test_setup_keeps_existing_secrets_unless_forced_to_rotate() -> None:
    first, first_secrets = apply_first_run_setup(EXAMPLE_ENV)

    second, second_secrets = apply_first_run_setup(first.text)
    assert parse_env_text(second.text) == parse_env_text(first.text)
    assert set(second.skipped) == set(ENV_KEYS)
    assert second.applied == ()
    assert second_secrets.database_password != first_secrets.database_password  # new draw, unused

    forced, _forced_secrets = apply_first_run_setup(first.text, overwrite=True)
    forced_values = parse_env_text(forced.text)
    assert forced_values["POSTGRES_PASSWORD"] != first_secrets.database_password
    assert forced_values["AUTH_JWT_SECRET"] != first_secrets.auth_jwt_secret
    assert make_url(forced_values["DATABASE_URL"]).password == forced_values["POSTGRES_PASSWORD"]


def test_setup_replaces_a_placeholder_password_but_not_a_real_one() -> None:
    placeholder = "POSTGRES_PASSWORD=decision_assistant\nAUTH_JWT_SECRET=\n"
    update, generated = apply_first_run_setup(placeholder)
    assert parse_env_text(update.text)["POSTGRES_PASSWORD"] == generated.database_password

    # The DB26 case: a URL whose password was rotated by hand against the live database while
    # POSTGRES_PASSWORD still holds the old value. Rewriting it would replace a working connection
    # string with a guess, so it is left alone — the one place this step deliberately does nothing.
    hand_rotated = (
        "POSTGRES_PASSWORD=oldpassword\n"
        "AUTH_JWT_SECRET=\n"
        "DATABASE_URL=postgresql+asyncpg://decision_assistant:rotatedbyhand@db:5432/decision_assistant\n"
    )
    update, _generated = apply_first_run_setup(hand_rotated)
    assert parse_env_text(update.text)["DATABASE_URL"] == (
        "postgresql+asyncpg://decision_assistant:rotatedbyhand@db:5432/decision_assistant"
    )
    # The mixed case the operator reads in the summary: the blank JWT secret is filled, the two
    # already-real values are reported as kept rather than silently rewritten.
    assert update.applied == ("AUTH_JWT_SECRET",)
    assert set(update.skipped) == {"POSTGRES_PASSWORD", "DATABASE_URL"}


def test_setup_appends_a_key_that_is_absent_entirely() -> None:
    update = update_env_text(
        "POSTGRES_DB=decision_assistant\n", {"AUTH_JWT_SECRET": "abc"}, overwrite=False
    )

    assert update.text == "POSTGRES_DB=decision_assistant\n\nAUTH_JWT_SECRET=abc\n"
    assert update.applied == ("AUTH_JWT_SECRET",)


@pytest.mark.parametrize(
    ("env_text", "expected"),
    [
        (EXAMPLE_ENV, False),
        ("AUTH_JWT_SECRET=x\nPOSTGRES_PASSWORD=decision_assistant\n", False),
        ("AUTH_JWT_SECRET=x\nPOSTGRES_PASSWORD=realsecret\n", True),
        ("AUTH_JWT_SECRET=x\nPOSTGRES_PASSWORD=realsecret\nDATABASE_URL=not a url\n", True),
        (
            "AUTH_JWT_SECRET=x\nPOSTGRES_PASSWORD=realsecret\n"
            "DATABASE_URL=postgresql+asyncpg://decision_assistant:decision_assistant@db:5432/d\n",
            False,
        ),
    ],
)
def test_status_decides_from_the_placeholder_not_from_presence(
    env_text: str, expected: bool
) -> None:
    assert env_is_configured(parse_env_text(env_text)) is expected


def test_cli_writes_the_updated_env_to_stdout_and_logs_no_secret_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # pytest replaces sys.stdin with a reader that raises while output is captured, so the CLI's
    # "read the current .env" contract is satisfied with an explicit stream.
    monkeypatch.setattr("sys.stdin", io.StringIO(EXAMPLE_ENV))
    settings = _settings(tmp_path)
    handler = configure_logging(settings)
    try:
        exit_code = main(["env"], settings=settings)
    finally:
        _detach(handler)

    captured = capsys.readouterr()
    assert exit_code == 0
    written = parse_env_text(captured.out)
    assert make_url(written["DATABASE_URL"]).password == written["POSTGRES_PASSWORD"]

    # `status` reads the same text and reports the decision without printing anything sensitive.
    monkeypatch.setattr("sys.stdin", io.StringIO(captured.out))
    settings = _settings(tmp_path)
    handler = configure_logging(settings)
    try:
        assert main(["status"], settings=settings) == 0
    finally:
        _detach(handler)
    status_out = capsys.readouterr().out
    # The module's own log line goes to the file, not to stdout, which is what lets the host script
    # redirect stdout straight over `.env`.
    assert status_out.strip() == '{"configured": true}'

    log_text = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    for secret in (written["POSTGRES_PASSWORD"], written["AUTH_JWT_SECRET"], FAKE_GEMINI_KEY):
        assert secret not in log_text
    # The URL carries the password, so it must not be logged either.
    assert written["DATABASE_URL"] not in log_text
    # Names, though, are what makes the log useful — the step reports what it touched.
    assert "POSTGRES_PASSWORD" in log_text
    assert "AUTH_JWT_SECRET" in log_text
