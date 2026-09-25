from pathlib import Path
from unittest.mock import patch

import pytest

from decision_assistant import migrations


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
