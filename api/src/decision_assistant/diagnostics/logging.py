"""Rotating, secret-scrubbed application logging (T056, US7; FR-017).

The app writes its own logs to `<log_directory>/decision-assistant.log` and rotates them, so an
operator can attach them to a bug report without grepping secrets out by hand first. Scrubbing is
two-layered on purpose:

* `SecretScrubbingFilter` cleans the *record* (`msg`, `args`, `exc_text`, `stack_info`) before any
  handler sees it, so a handler added elsewhere cannot leak the value either.
* `SecretScrubbingFormatter` cleans the *rendered* message, exception traceback, and stack, which
  the filter cannot reach: a traceback is only turned into text by the formatter, so a secret in
  `raise ValueError(api_key)` never appears in a record attribute the filter could rewrite.

Scrubbing is value-based, not shape-based: every non-empty configured secret value is replaced
wherever it appears, with no minimum length and no "looks like a secret" heuristic. A short
secret is still a secret, and a heuristic that guesses wrong is a leak. `scrub_values` widens
"value" to include the *encoded and derived* renderings a library could log instead of the raw
string — the percent-encoded form, the base64 form, and URL userinfo (DB56).
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from urllib.parse import quote

from sqlalchemy.engine import make_url

from decision_assistant.config import Settings

LOG_FILE_NAME = "decision-assistant.log"
REDACTED = "[REDACTED]"

#: Attached to the handlers this module installs, so a later `configure_logging` call (tests call
#: `create_app` repeatedly) can find and replace its own handlers without touching ones a caller,
#: uvicorn, or pytest installed.
_HANDLER_MARKER = "_decision_assistant_file_handler"

#: Loggers this module attaches the file handler to. Deliberately excludes `uvicorn.error`: it
#: carries no handlers of its own and propagates to `uvicorn`, which does have ours, so attaching
#: there as well wrote every startup line and traceback twice (DB61). `uvicorn.access` is included
#: because uvicorn gives it `propagate = False`, so it never reaches `uvicorn`.
_LOG_TARGETS = ("", "uvicorn", "uvicorn.access")

#: Loggers whose propagation is forced off. Both are already non-propagating under uvicorn's own
#: logging config; enforcing it here keeps the file's line count stable when this is called without
#: that config (tests, `python -m` scripts), where the default `propagate = True` would send the
#: same record to both the per-logger handler and the root handler.
_NON_PROPAGATING_LOGGERS = ("uvicorn", "uvicorn.access")

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _database_password(database_url: str) -> str | None:
    """Return the password embedded in `database_url`, or None if there is none/unparsable."""
    try:
        return make_url(database_url).password
    except Exception:
        return None


def secret_values(settings: Settings) -> tuple[str, ...]:
    """Every configured secret value, longest first.

    Longest first so a secret that contains another one is replaced whole rather than leaving the
    longer value's tail behind. Duplicates and empty values are dropped.
    """
    candidates: list[str] = []
    for secret in (
        settings.gemini_api_key,
        settings.auth_jwt_secret,
    ):
        if secret is not None and secret.get_secret_value():
            candidates.append(secret.get_secret_value())
    password = _database_password(settings.database_url)
    if password:
        candidates.append(password)
    return tuple(sorted(set(candidates), key=len, reverse=True))


def scrub_secrets(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of every secret value in `text` with `[REDACTED]`."""
    scrubbed = text
    for secret in secrets:
        if secret:
            scrubbed = scrubbed.replace(secret, REDACTED)
    return scrubbed


def _derived_encodings(value: str) -> list[str]:
    """Renderings of `value` that a library or client could log instead of the raw secret."""
    forms = [value]
    quoted = quote(value, safe="")
    if quoted != value:
        forms.append(quoted)
    forms.append(base64.b64encode(value.encode("utf-8")).decode("ascii"))
    return forms


def _credentials_in_url(url: str | None) -> list[str]:
    """The password, and `user:password`, from a URL's userinfo (DB56).

    Only the password half is treated as secret; the username is not, and redacting it would make
    logs harder to read for no security gain.
    """
    if not url:
        return []
    try:
        parsed = make_url(url)
    except Exception:
        return []
    password = parsed.password
    if not password:
        return []
    values = [password]
    if parsed.username:
        values.append(f"{parsed.username}:{password}")
    return values


def scrub_values(settings: Settings) -> tuple[str, ...]:
    """Every value to scrub from a log record: the configured secrets and their derived encodings.

    Exact-value scrubbing alone misses the forms code actually logs: a percent-encoded password
    inside a connection string, a base64 credential header, URL userinfo (DB56). Encoding each
    secret in the shapes that survive a transform closes that gap with no "looks like a secret"
    heuristic, which would guess wrong in both directions.
    """
    raw = list(secret_values(settings))
    raw.extend(_credentials_in_url(settings.ollama_base_url))
    raw.extend(_credentials_in_url(settings.database_url))
    candidates: list[str] = []
    for value in raw:
        candidates.extend(_derived_encodings(value))
    return tuple(sorted({value for value in candidates if value}, key=len, reverse=True))


class SecretScrubbingFilter(logging.Filter):
    """Rewrite a log record's own string fields so no handler can emit a secret."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub_secrets(record.msg, self._secrets)
        if isinstance(record.args, dict):
            record.args = {
                key: scrub_secrets(value, self._secrets) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(
                scrub_secrets(value, self._secrets) if isinstance(value, str) else value
                for value in record.args
            )
        for attribute in ("exc_text", "stack_info"):
            value = getattr(record, attribute, None)
            if isinstance(value, str):
                setattr(record, attribute, scrub_secrets(value, self._secrets))
        return True


class SecretScrubbingFormatter(logging.Formatter):
    """Scrub the rendered message, exception traceback, and stack.

    Only those three parts are scrubbed, not the whole formatted line: a formatter that rewrote
    the entire line would also mangle the logger name when the logger name happens to contain a
    configured secret value (`decision_assistant.main` while the shared placeholder password is
    still in `.env`, for example), which would make logs harder to read for no security gain.
    """

    def __init__(self, fmt: str | None = None, *, secrets: Iterable[str] = ()) -> None:
        super().__init__(fmt=fmt)
        self._secrets = tuple(secrets)

    def formatMessage(self, record: logging.LogRecord) -> str:
        return scrub_secrets(super().formatMessage(record), self._secrets)

    def formatException(
        self, ei: tuple[type[BaseException], BaseException, object] | tuple[None, None, None]
    ) -> str:
        return scrub_secrets(super().formatException(ei), self._secrets)

    def formatStack(self, stack_info: str) -> str:
        return scrub_secrets(super().formatStack(stack_info), self._secrets)


def configure_logging(settings: Settings) -> RotatingFileHandler:
    """Attach a rotating, scrubbed file handler to the root and uvicorn loggers.

    Idempotent in two directions: handlers this function installed on a previous call are replaced
    (so calling it twice, or once per `create_app`, cannot duplicate log lines or leave the file
    open twice), and each record reaches the file exactly once — the target loggers in
    `_LOG_TARGETS` are the only ones holding a file handler, and `_NON_PROPAGATING_LOGGERS` do not
    forward their records to the root logger as well (DB61).
    """
    targets = [logging.getLogger(name) for name in _LOG_TARGETS]
    for name in _NON_PROPAGATING_LOGGERS:
        logging.getLogger(name).propagate = False

    stale: dict[int, logging.Handler] = {}
    for logger in targets:
        for existing in list(logger.handlers):
            if getattr(existing, _HANDLER_MARKER, False):
                logger.removeHandler(existing)
                stale[id(existing)] = existing
    for handler in stale.values():
        handler.close()

    secrets = scrub_values(settings)
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.log_directory / LOG_FILE_NAME,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    setattr(handler, _HANDLER_MARKER, True)
    handler.addFilter(SecretScrubbingFilter(secrets))
    handler.setFormatter(SecretScrubbingFormatter(_FORMAT, secrets=secrets))

    for logger in targets:
        logger.addHandler(handler)
    logging.getLogger().setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    return handler
