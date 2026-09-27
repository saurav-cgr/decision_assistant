"""Diagnostics bundle assembly (T057, US7/FR-018).

The bundle exists so a user can attach one file to a bug report without hand-redacting it, so the
config dump is an **allowlist doubled with two independent guards**: only fields named in
`BUNDLE_SETTINGS_FIELDS` are ever included, a field whose name looks credential-bearing is refused
even if it is listed, and only plain JSON scalars survive (a `SecretStr` is not one). Every guard has
to fail before a secret ships — a field added to `Settings` tomorrow is excluded until someone
lists it, listing a `SecretStr` field by mistake still yields nothing, and listing a plain-string
credential such as `database_url` is caught by the name rule. Secrets, connection strings, and
filesystem paths are all deliberately absent: paths are not needed to diagnose a provider or parser
problem, and `DATABASE_URL`/`OLLAMA_BASE_URL` can carry credentials in their userinfo.

Shipped as two functions so the interesting half is testable without a database: `assemble_bundle` is
pure, and `build_bundle` is the async entry point that also reads the database's current revision.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from decision_assistant.config import Settings
from decision_assistant.diagnostics.logging import LOG_FILE_NAME
from decision_assistant.migrations import current_db_revision
from decision_assistant.version import get_app_version

#: Settings fields safe to ship. Deliberately excludes every secret (`auth_jwt_secret`,
#: `gemini_api_key`, `auth_jwt_secret`), every URL (`database_url`, `ollama_base_url`), and
#: every filesystem path (`upload_directory`, `backup_directory`, `log_directory`).
BUNDLE_SETTINGS_FIELDS: tuple[str, ...] = (
    "generation_provider",
    "embedding_provider",
    "gemini_generation_model",
    "gemini_embedding_model",
    "gemini_embedding_dimension",
    "gemini_embedding_config_version",
    "gemini_generation_prompt_version",
    "ollama_generation_model",
    "ollama_embedding_model",
    "ollama_embedding_dimension",
    "chunking_profile_preset",
    "retrieval_unit_strategy",
    "rerank_enabled",
    "max_upload_bytes",
    "max_pdf_pages",
    "model_timeout_seconds",
    "model_retry_count",
    "pdf_parse_timeout_seconds",
    "pdf_parse_concurrency",
    "max_ingestion_attempts",
    "max_evaluation_attempts",
    "pre_migration_backup_retention",
    "auth_access_token_ttl_minutes",
    "log_level",
    "log_max_bytes",
    "log_backup_count",
    "frontend_origin",
)

#: Second guard: a field name containing any of these is refused even when it is listed in the
#: allowlist above, because `database_url` and `ollama_base_url` are plain strings whose userinfo can
#: carry a password.
_CREDENTIAL_NAME_PARTS = ("secret", "password", "api_key", "token", "url")


def sanitized_settings(settings: Settings) -> dict[str, Any]:
    """The allowlisted subset of `settings`, values restricted to JSON scalars."""
    dumped = settings.model_dump()
    sanitized: dict[str, Any] = {}
    for field in BUNDLE_SETTINGS_FIELDS:
        if any(part in field for part in _CREDENTIAL_NAME_PARTS):
            continue
        value = dumped.get(field)
        if isinstance(value, str | int | float | bool) or value is None:
            sanitized[field] = value
    return sanitized


def _log_files(log_directory: Path) -> list[Path]:
    """The active log plus its rotated siblings, oldest-name-first, or nothing if never configured."""
    if not log_directory.is_dir():
        return []
    return sorted(
        path for path in log_directory.glob(f"{LOG_FILE_NAME}*") if path.is_file()
    )


def assemble_bundle(settings: Settings, *, database_revision: str) -> bytes:
    """Build the zip in memory: version, migration revision, sanitized settings, and logs."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("version.txt", f"{get_app_version()}\n")
        archive.writestr("alembic-current.txt", f"{database_revision}\n")
        archive.writestr(
            "settings.json",
            json.dumps(sanitized_settings(settings), indent=2, sort_keys=True) + "\n",
        )
        for path in _log_files(settings.log_directory):
            archive.write(path, arcname=f"logs/{path.name}")
    return buffer.getvalue()


async def build_bundle(settings: Settings) -> bytes:
    """Assemble the bundle, reading the database's current migration revision first.

    A database that cannot be reached must not fail this request (DB61): an operator whose stack is
    half down is exactly who needs the bundle. The revision is reported as unavailable instead of
    the whole download turning into a 500.
    """
    try:
        revision = await current_db_revision(settings)
    except Exception:  # noqa: BLE001 - any failure here must not hide the logs
        return assemble_bundle(
            settings, database_revision="unavailable (database unreachable)"
        )
    return assemble_bundle(
        settings,
        database_revision=revision if revision is not None else "no revisions applied",
    )
