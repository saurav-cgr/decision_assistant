from pathlib import Path

from alembic import command
from alembic.config import Config

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
