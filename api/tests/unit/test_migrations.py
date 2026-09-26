from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from decision_assistant import migrations
from decision_assistant.config import Settings


def test_upgrade_to_head_raises_actionable_error_when_ini_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(migrations, "_ALEMBIC_INI", tmp_path / "alembic.ini")

    with pytest.raises(FileNotFoundError, match="alembic.ini not found"):
        migrations.upgrade_to_head()


def test_upgrade_to_head_uses_cwd_relative_ini(tmp_path, monkeypatch):
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text("[alembic]\n")
    monkeypatch.setattr(migrations, "_ALEMBIC_INI", ini_path)

    with patch.object(migrations.command, "upgrade") as mock_upgrade:
        migrations.upgrade_to_head()

    assert mock_upgrade.call_count == 1
    config_arg, revision_arg = mock_upgrade.call_args.args
    assert Path(config_arg.config_file_name) == ini_path
    assert revision_arg == "head"


def test_is_upgrade_pending_true_when_current_revision_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migrations, "_head_revision", lambda: "0012_head")
    monkeypatch.setattr(
        migrations, "_current_db_revision", AsyncMock(return_value="0011_prior")
    )

    assert migrations.is_upgrade_pending(Settings()) is True


def test_is_upgrade_pending_false_when_current_revision_matches_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migrations, "_head_revision", lambda: "0012_head")
    monkeypatch.setattr(
        migrations, "_current_db_revision", AsyncMock(return_value="0012_head")
    )

    assert migrations.is_upgrade_pending(Settings()) is False


def test_is_upgrade_pending_true_on_empty_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No alembic_version table yet: MigrationContext.get_current_revision()
    # reports None. An empty database is still pending its first migration.
    monkeypatch.setattr(migrations, "_head_revision", lambda: "0012_head")
    monkeypatch.setattr(
        migrations, "_current_db_revision", AsyncMock(return_value=None)
    )

    assert migrations.is_upgrade_pending(Settings()) is True
