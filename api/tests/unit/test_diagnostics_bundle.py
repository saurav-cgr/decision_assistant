"""T055 (US7/FR-018): the diagnostics bundle must be safe to paste into a bug report.

The property under test is negative — no configured secret value appears anywhere in the archive —
so the tests assert against the assembled bytes for every configured secret, not just against the
shape of the config dump. The dump is also probed adversarially by allowlisting credential fields on
purpose, which is exactly the mistake a future edit could make.
"""

import io
import json
import zipfile
from pathlib import Path

from pydantic import SecretStr

from decision_assistant.config import Settings
from decision_assistant.diagnostics import bundle as bundle_module
from decision_assistant.diagnostics.bundle import (
    BUNDLE_SETTINGS_FIELDS,
    assemble_bundle,
    sanitized_settings,
)
from decision_assistant.diagnostics.logging import LOG_FILE_NAME
from decision_assistant.version import get_app_version

_GEMINI_KEY = "fake-gemini-key-for-bundle"
_JWT_SECRET = "fake-jwt-secret-for-bundle"
_DB_PASSWORD = "fake-db-password-for-bundle"
_DATABASE_URL = f"postgresql+asyncpg://db_user:{_DB_PASSWORD}@db:5432/decision_assistant"


def _settings(**overrides: object) -> Settings:
    fields: dict[str, object] = {
        "gemini_api_key": SecretStr(_GEMINI_KEY),
        "auth_jwt_secret": SecretStr(_JWT_SECRET),
        "database_url": _DATABASE_URL,
    }
    fields.update(overrides)
    return Settings(**fields)


def _member_texts(bundle: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        return {
            name: archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
        }


def test_settings_dump_is_allowlisted_and_scalar_only() -> None:
    dump = sanitized_settings(_settings())

    assert set(dump) <= set(BUNDLE_SETTINGS_FIELDS)
    for value in dump.values():
        assert value is None or isinstance(value, str | int | float | bool), value
    # The three useful provider facts are present, so the dump is not merely empty.
    assert dump["generation_provider"] == "gemini"
    assert dump["embedding_provider"] == "gemini"
    assert dump["chunking_profile_preset"]


def test_bundle_contains_no_configured_secret_value_anywhere() -> None:
    settings = _settings()
    bundle = assemble_bundle(settings, database_revision="0016_evidence_quote (head)")
    texts = _member_texts(bundle)

    assert "settings.json" in texts
    for secret in (_GEMINI_KEY, _JWT_SECRET, _DB_PASSWORD):
        assert all(secret not in text for text in texts.values()), secret
    assert _DATABASE_URL not in texts["settings.json"]
    # The connection string's username is not a secret, but it arrives with the password, so the
    # whole URL stays out rather than being partially redacted.
    assert "db_user" not in texts["settings.json"]


def test_a_mistakenly_allowlisted_credential_field_still_ships_nothing(
    monkeypatch,
) -> None:
    # Simulates the realistic future mistake: someone adds a credential field to the allowlist.
    # Asserted on the dump itself rather than through the archive, so a failure names the leaking
    # field instead of surfacing as a serialization error.
    monkeypatch.setattr(
        bundle_module,
        "BUNDLE_SETTINGS_FIELDS",
        (
            *BUNDLE_SETTINGS_FIELDS,
            "gemini_api_key",
            "auth_jwt_secret",
            "database_url",
            "ollama_base_url",
        ),
    )
    settings = _settings()
    dump = sanitized_settings(settings)

    for field in (
        "gemini_api_key",
        "auth_jwt_secret",
        "database_url",
        "ollama_base_url",
    ):
        assert field not in dump, field
    serialized = json.dumps(dump)
    for secret in (_GEMINI_KEY, _JWT_SECRET, _DB_PASSWORD):
        assert secret not in serialized, secret


def test_log_files_are_included_including_rotated_ones(tmp_path: Path) -> None:
    log_directory = tmp_path / "logs"
    log_directory.mkdir()
    (log_directory / LOG_FILE_NAME).write_text("current line\n")
    (log_directory / f"{LOG_FILE_NAME}.1").write_text("older line\n")
    (log_directory / "unrelated.txt").write_text("not a log\n")

    texts = _member_texts(
        assemble_bundle(
            _settings(log_directory=log_directory), database_revision="head"
        )
    )

    assert texts["logs/decision-assistant.log"] == "current line\n"
    assert texts["logs/decision-assistant.log.1"] == "older line\n"
    assert all("unrelated" not in name for name in texts)


def test_bundle_still_builds_when_no_log_directory_exists(tmp_path: Path) -> None:
    texts = _member_texts(
        assemble_bundle(
            _settings(log_directory=tmp_path / "never-created"), database_revision="head"
        )
    )

    assert all(not name.startswith("logs/") for name in texts)
    assert {"version.txt", "alembic-current.txt", "settings.json"} <= set(texts)


async def test_bundle_survives_a_database_outage(tmp_path: Path, monkeypatch) -> None:
    # DB61: the bundle is most useful when the stack is half down, so a database that cannot be
    # reached must not turn the download into a 500.
    async def _unreachable(settings: Settings) -> str | None:
        raise OSError("database is down")

    monkeypatch.setattr(bundle_module, "current_db_revision", _unreachable)

    texts = _member_texts(await bundle_module.build_bundle(_settings(log_directory=tmp_path)))

    assert texts["alembic-current.txt"] == "unavailable (database unreachable)\n"
    assert "settings.json" in texts


def test_bundle_reports_the_app_version_and_the_database_revision() -> None:
    texts = _member_texts(
        assemble_bundle(_settings(), database_revision="0016_evidence_quote (head)")
    )

    assert texts["version.txt"] == f"{get_app_version()}\n"
    # Reported verbatim, so a bundle states which schema the database was actually on.
    assert texts["alembic-current.txt"] == "0016_evidence_quote (head)\n"


def test_bundle_is_a_readable_zip() -> None:
    bundle = assemble_bundle(_settings(), database_revision="head")

    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert archive.testzip() is None
        assert {"version.txt", "alembic-current.txt", "settings.json"} <= set(
            archive.namelist()
        )
