from functools import lru_cache
from importlib import metadata

_PACKAGE_NAME = "decision-assistant"
_FALLBACK_VERSION = "0.0.0-unknown"


@lru_cache
def get_app_version() -> str:
    """Return the installed package version (`project.version` in pyproject.toml).

    Reads installed distribution metadata rather than parsing pyproject.toml
    directly, so it works the same way under both the editable dev install
    and T001's non-editable production install (see M-020 — a path computed
    from `__file__` breaks under the latter).
    """
    try:
        return metadata.version(_PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return _FALLBACK_VERSION
