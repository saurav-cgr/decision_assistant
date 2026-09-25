import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from decision_assistant.config import Settings
from decision_assistant.db import create_engine

# api/alembic.ini. Resolved from the process's current working directory, not
# from this file's own location (checker V46): both the Dockerfile (`WORKDIR
# /workspace/api`) and compose.yaml (`working_dir: /workspace/api`) pin the
# api service's cwd there, but a `pip install .` (non-editable, T001's
# production install) copies this file into site-packages, so a `__file__`-
# relative path would resolve to the wrong location outside an editable
# install.
_ALEMBIC_INI = Path.cwd() / "alembic.ini"


def upgrade_to_head() -> None:
    """Run `alembic upgrade head` programmatically.

    `alembic/env.py` derives its own database URL from `config.get_settings()`
    (the same cached Settings the rest of the app uses), so this takes no
    URL argument — passing one would be silently ignored by env.py anyway.

    Synchronous and blocking (`env.py` calls `asyncio.run()` internally), so
    callers running inside an existing event loop must invoke this via a
    worker thread (e.g. `asyncio.to_thread`), not call it directly.
    """
    if not _ALEMBIC_INI.is_file():
        raise FileNotFoundError(
            f"alembic.ini not found at {_ALEMBIC_INI} (cwd={Path.cwd()}). "
            "upgrade_to_head() expects the process's working directory to be "
            "api/ (both the Dockerfile and compose.yaml pin this for the api "
            "service)."
        )
    config = Config(str(_ALEMBIC_INI))
    command.upgrade(config, "head")


def _head_revision() -> str | None:
    config = Config(str(_ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


async def _current_db_revision(settings: Settings) -> str | None:
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync_connection: MigrationContext.configure(
                    sync_connection
                ).get_current_revision()
            )
    finally:
        await engine.dispose()


def is_upgrade_pending(settings: Settings) -> bool:
    """Return True if the database is not already at the head revision.

    Gates T014's pre-migration backup (FR-005) so it only fires when
    `upgrade_to_head()` is actually about to change the schema, not on every
    boot. A backup taken on a no-op restart would rotate out (per
    `pre_migration_backup_retention`) before a real migration ever needed it
    (checker V63: retention 2 and 5 both lost the only pre-migration archive
    to unconditional no-op-restart backups).

    Synchronous and blocking; callers inside an event loop must invoke this
    via a worker thread (e.g. `asyncio.to_thread`), same as `upgrade_to_head`.
    An empty database (no `alembic_version` table yet) reports `None` as its
    current revision, which is treated as pending.
    """
    return asyncio.run(_current_db_revision(settings)) != _head_revision()
