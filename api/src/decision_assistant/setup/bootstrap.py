"""First-run secret generation and `.env` rewriting (US5/FR-013, T041).

`scripts/setup.sh` pipes the current host `.env` into this module (via a one-shot container) and
redirects the module's stdout back over `.env`; this module never touches the host filesystem itself.
Everything that decides *what* goes into `.env` therefore lives here, where T040 can unit-test it.

Two properties are deliberate, not incidental:

* Generated secrets are **hex**. The same value has to survive three contexts — a `.env` line, a SQL
  literal for `ALTER ROLE`, and a URL password — and hex needs no escaping or quoting in any of them.
* Only key *names* and counts are ever logged, never values (FR-013/T040).
"""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from decision_assistant.config import PLACEHOLDER_DB_CREDENTIALS, Settings, get_settings
from decision_assistant.diagnostics.logging import configure_logging

logger = logging.getLogger("decision_assistant.setup")

#: The keys this module owns. `AUTH_BOOTSTRAP_*` is deliberately absent: US5 replaces env bootstrap
#: credentials with the first-run password flow (T042), so setup must not resurrect them.
ENV_KEYS = ("POSTGRES_PASSWORD", "AUTH_JWT_SECRET", "DATABASE_URL")

DEFAULT_DATABASE_HOST = "db"
DEFAULT_DATABASE_PORT = 5432
DEFAULT_POSTGRES_USER = "decision_assistant"
DEFAULT_POSTGRES_DB = "decision_assistant"

#: 32 bytes = 256 bits, hex-encoded to 64 characters.
SECRET_BYTES = 32


class SetupError(RuntimeError):
    """Raised when setup cannot produce a usable configuration."""


@dataclass(frozen=True, slots=True)
class FirstRunSecrets:
    auth_jwt_secret: str
    database_password: str


@dataclass(frozen=True, slots=True)
class EnvUpdate:
    text: str
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


def generate_secret(*, nbytes: int = SECRET_BYTES) -> str:
    if nbytes < 16:
        raise ValueError("Refusing to generate a secret shorter than 16 bytes")
    return secrets.token_hex(nbytes)


def generate_first_run_secrets() -> FirstRunSecrets:
    """Two independent draws, so no two runs (or installs) can share a value."""
    return FirstRunSecrets(
        auth_jwt_secret=generate_secret(),
        database_password=generate_secret(),
    )


def _entries(text: str) -> Iterator[tuple[int, str, str]]:
    """Yield `(line index, key, value)` for every `KEY=value` line, skipping comments and blanks.

    A surrounding pair of quotes is stripped from the value, matching how `dotenv` and Compose read
    the file.
    """
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        yield index, key.strip(), value


def parse_env_text(text: str) -> dict[str, str]:
    """The key/value pairs of an `.env` file; last occurrence wins."""
    return {key: value for _, key, value in _entries(text)}


def _is_placeholder(value: str | None) -> bool:
    return value is not None and value.strip() in PLACEHOLDER_DB_CREDENTIALS


def _needs_value(value: str | None) -> bool:
    return value is None or not value.strip() or _is_placeholder(value)


def _parsed_url(value: str | None) -> URL | None:
    if not value or not value.strip():
        return None
    try:
        return make_url(value.strip())
    except ArgumentError:
        return None


def env_is_configured(values: Mapping[str, str]) -> bool:
    """True when `.env` already holds real (non-placeholder) first-run secrets.

    Only the DATABASE_URL *password* is inspected, never its username: `decision_assistant` is the
    legitimate default username, so treating it as a placeholder would report every healthy install
    as unconfigured. The shared credential DB8/DB26 cares about is the password.
    """
    if _needs_value(values.get("AUTH_JWT_SECRET")):
        return False
    if _needs_value(values.get("POSTGRES_PASSWORD")):
        return False
    url = _parsed_url(values.get("DATABASE_URL"))
    if url is None:
        # A blank or unparsable DATABASE_URL is acceptable here: `render_database_url` derives one
        # from the POSTGRES_* names, which the two checks above have already accepted.
        return True
    return not _is_placeholder(url.password)


def render_database_url(values: Mapping[str, str], password: str) -> str:
    """The connection string for `password`, keeping the operator's host/port/database choices.

    Falls back to Compose's own defaults when DATABASE_URL is blank or unusable, so a fresh install
    from `.env.example` (where that line is intentionally empty) still produces a working URL.
    """
    url = _parsed_url(values.get("DATABASE_URL"))
    if url is None or not url.host or not url.database or not url.username:
        user = (values.get("POSTGRES_USER") or "").strip() or DEFAULT_POSTGRES_USER
        database = (values.get("POSTGRES_DB") or "").strip() or DEFAULT_POSTGRES_DB
        url = URL.create(
            drivername="postgresql+asyncpg",
            username=user,
            password=None,
            host=DEFAULT_DATABASE_HOST,
            port=DEFAULT_DATABASE_PORT,
            database=database,
        )
    return url.set(password=quote(password, safe="")).render_as_string(hide_password=False)


def update_env_text(
    text: str,
    values: Mapping[str, str],
    *,
    overwrite: bool,
    keep: Collection[str] = (),
) -> EnvUpdate:
    """Rewrite `.env` in place, preserving comments, ordering and unrelated keys.

    `keep` names keys the caller has already decided to leave exactly as they are; they are reported
    in `skipped` and never written, which is how `apply_first_run_setup` tells the operator what it
    did **not** touch. With `overwrite=False` an unlisted key that already holds a real value is
    skipped on the same terms, so re-running setup cannot silently rotate a working install.
    """
    pending = dict(values)
    for key in keep:
        pending.pop(key, None)

    applied: list[str] = []
    skipped_by_rule: list[str] = []
    lines = text.splitlines()

    for index, key, current in _entries(text):
        if key not in pending:
            continue
        if not overwrite and not _needs_value(current):
            skipped_by_rule.append(key)
            pending.pop(key)
            continue
        lines[index] = f"{key}={pending.pop(key)}"
        applied.append(key)

    if pending:
        if lines and lines[-1].strip():
            lines.append("")
        for key, value in pending.items():
            lines.append(f"{key}={value}")
            applied.append(key)

    trailing = "\n" if text.endswith("\n") or not text else ""
    return EnvUpdate(
        text="\n".join(lines) + trailing,
        applied=tuple(applied),
        skipped=tuple(skipped_by_rule) + tuple(keep),
    )


def apply_first_run_setup(
    text: str, *, overwrite: bool = False
) -> tuple[EnvUpdate, FirstRunSecrets]:
    """Fill (or, with `overwrite`, rotate) the first-run secrets in an `.env` file's text.

    `EnvUpdate.applied` and `EnvUpdate.skipped` are what the operator is told, so a key that already
    holds a real value has to appear in `skipped`: silently reporting "applied" for all three keys
    would make it impossible to see that an install was left alone.
    """
    values = parse_env_text(text)
    generated = generate_first_run_secrets()

    updates: dict[str, str] = {}
    keep: list[str] = []
    for key, generated_value in (
        ("POSTGRES_PASSWORD", generated.database_password),
        ("AUTH_JWT_SECRET", generated.auth_jwt_secret),
    ):
        if overwrite or _needs_value(values.get(key)):
            updates[key] = generated_value
        else:
            keep.append(key)

    # DATABASE_URL must carry whichever password postgres will actually have. The one case that is
    # not knowable from here is an install whose URL already holds a real password that differs from
    # POSTGRES_PASSWORD (rotated by hand against the live database, DB26): rewriting it would replace
    # a working connection string with a guess, so it is left exactly as it is and reported as kept.
    password = updates.get("POSTGRES_PASSWORD") or (values.get("POSTGRES_PASSWORD") or "").strip()
    url = _parsed_url(values.get("DATABASE_URL"))
    url_password = url.password if url is not None else None
    if not overwrite and url_password and not _is_placeholder(url_password):
        keep.append("DATABASE_URL")
    else:
        updates["DATABASE_URL"] = render_database_url(values, password)

    # `overwrite=True` here because every value above is already the decision; the no-overwrite rule
    # was applied per key when choosing it, and `keep` records the keys it left alone.
    return update_env_text(text, updates, overwrite=True, keep=keep), generated


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m decision_assistant.setup.bootstrap",
        description=(
            "First-run secret generation. `env` reads an .env file on stdin and writes the updated "
            "file to stdout; `status` reports whether it already holds real secrets."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    env_parser = subcommands.add_parser("env", help="rewrite an .env file from stdin to stdout")
    env_parser.add_argument(
        "--force",
        action="store_true",
        help="rotate secrets that are already set (otherwise they are kept as they are)",
    )
    subcommands.add_parser("status", help="print {'configured': bool} for the .env on stdin")
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    # Configured here as well as in the app: a setup run happens before any app process exists, and
    # going through the same scrubbing formatter is what makes "no secret value reaches the log" true
    # for this path too (T040's second half).
    configure_logging(settings if settings is not None else get_settings())

    original = sys.stdin.read()
    if args.command == "status":
        json.dump({"configured": env_is_configured(parse_env_text(original))}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    update, _generated = apply_first_run_setup(original, overwrite=bool(args.force))
    sys.stdout.write(update.text)
    # Key names and counts only — never a value, and never a provider API key (FR-013; T040 asserts
    # both halves against the produced log file).
    logger.info(
        "setup: generated %d secret(s); applied %d key(s): %s",
        len(ENV_KEYS),
        len(update.applied),
        ", ".join(update.applied) or "none",
    )
    if update.skipped:
        logger.info("setup: kept existing values for %s", ", ".join(update.skipped))
    logger.info("setup: provider API keys are neither read nor written by this step")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI test
    raise SystemExit(main())
