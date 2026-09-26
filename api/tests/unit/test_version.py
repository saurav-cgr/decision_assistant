from importlib import metadata
from unittest.mock import patch

from decision_assistant import version


def test_get_app_version_reads_installed_package_metadata() -> None:
    version.get_app_version.cache_clear()

    result = version.get_app_version()

    assert result == metadata.version("decision-assistant")


def test_get_app_version_falls_back_when_package_not_found() -> None:
    version.get_app_version.cache_clear()

    with patch.object(
        metadata, "version", side_effect=metadata.PackageNotFoundError
    ):
        result = version.get_app_version()

    assert result == "0.0.0-unknown"
    version.get_app_version.cache_clear()
