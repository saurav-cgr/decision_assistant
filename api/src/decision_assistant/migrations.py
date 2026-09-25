from pathlib import Path

from alembic import command
from alembic.config import Config

# api/alembic.ini, resolved from this file's location so it works regardless
# of the process's current working directory.
_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def upgrade_to_head() -> None:
    """Run `alembic upgrade head` programmatically.

    `alembic/env.py` derives its own database URL from `config.get_settings()`
    (the same cached Settings the rest of the app uses), so this takes no
    URL argument — passing one would be silently ignored by env.py anyway.

    Synchronous and blocking (`env.py` calls `asyncio.run()` internally), so
    callers running inside an existing event loop must invoke this via a
    worker thread (e.g. `asyncio.to_thread`), not call it directly.
    """
    config = Config(str(_ALEMBIC_INI))
    command.upgrade(config, "head")
