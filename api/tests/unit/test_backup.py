import tarfile
from dataclasses import dataclass, field

import pytest

from decision_assistant import backup
from decision_assistant.config import Settings


@dataclass
class _FakeCompletedProcess:
    returncode: int
    stderr: bytes = field(default=b"")


def _make_settings(tmp_path, *, retention: int = 5) -> Settings:
    return Settings(
        backup_directory=tmp_path / "backups",
        upload_directory=tmp_path / "uploads",
        pre_migration_backup_retention=retention,
    )


def _seed_uploads(upload_directory) -> None:
    upload_directory.mkdir(parents=True)
    (upload_directory / "root.txt").write_text("root content")
    nested = upload_directory / "sub"
    nested.mkdir()
    (nested / "nested.txt").write_text("nested content")


def test_pg_dump_url_strips_asyncpg_driver_suffix() -> None:
    assert (
        backup._pg_dump_url("postgresql+asyncpg://u:p@db:5432/d")
        == "postgresql://u:p@db:5432/d"
    )


def test_pg_dump_url_leaves_plain_postgresql_url_unchanged() -> None:
    url = "postgresql://u:p@db:5432/d"
    assert backup._pg_dump_url(url) == url


def test_create_pre_migration_backup_produces_expected_archive_layout(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path)
    _seed_uploads(settings.upload_directory)

    def fake_run(cmd, *, stdout, stderr, check):
        assert "pg_dump" in cmd[0]
        stdout.write(b"-- fake dump\n")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(backup.subprocess, "run", fake_run)

    archive_path = backup.create_pre_migration_backup(settings)

    assert archive_path.parent == settings.backup_directory
    assert archive_path.name.startswith(backup._ARCHIVE_PREFIX)
    assert archive_path.suffixes[-2:] == [".tar", ".gz"]

    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
        assert set(names) == {"database.sql", "uploads.tar"}
        assert archive.extractfile("database.sql").read() == b"-- fake dump\n"

        uploads_member = archive.extractfile("uploads.tar")
        with tarfile.open(fileobj=uploads_member) as uploads:
            upload_names = set(uploads.getnames())
            assert "root.txt" in upload_names
            assert any(name.endswith("nested.txt") for name in upload_names)

    # Only the finished .tar.gz remains; the intermediate dump/uploads-tar
    # temp files were cleaned up.
    remaining = sorted(p.name for p in settings.backup_directory.iterdir())
    assert remaining == [archive_path.name]


def test_create_pre_migration_backup_raises_and_leaves_no_residue_on_pg_dump_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path)
    _seed_uploads(settings.upload_directory)

    def fake_run(cmd, *, stdout, stderr, check):
        stdout.write(b"partial, unusable dump")
        return _FakeCompletedProcess(returncode=1, stderr=b"pg_dump: fake failure")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)

    with pytest.raises(backup.PreMigrationBackupFailed, match="fake failure"):
        backup.create_pre_migration_backup(settings)

    # No partial archive, and the temp dump file was cleaned up rather than
    # left behind as filesystem clutter.
    assert list(settings.backup_directory.iterdir()) == []


def test_rotate_keeps_only_the_configured_retention_count(tmp_path) -> None:
    settings = _make_settings(tmp_path, retention=2)
    settings.backup_directory.mkdir(parents=True)
    names = [
        f"{backup._ARCHIVE_PREFIX}20260101T000000Z.tar.gz",
        f"{backup._ARCHIVE_PREFIX}20260102T000000Z.tar.gz",
        f"{backup._ARCHIVE_PREFIX}20260103T000000Z.tar.gz",
    ]
    for name in names:
        (settings.backup_directory / name).write_bytes(b"x")

    backup._rotate(settings)

    remaining = sorted(
        p.name for p in settings.backup_directory.glob(f"{backup._ARCHIVE_PREFIX}*.tar.gz")
    )
    assert remaining == names[1:]


def test_rotate_never_touches_a_different_archive_prefix(tmp_path) -> None:
    # scripts/backup.sh's user-triggered archives use a different filename
    # prefix specifically so this function's rotation can't prune them.
    settings = _make_settings(tmp_path, retention=1)
    settings.backup_directory.mkdir(parents=True)
    other_prefix = settings.backup_directory / "decision-assistant-backup-20260101T000000Z.tar.gz"
    other_prefix.write_bytes(b"x")
    own_old = settings.backup_directory / f"{backup._ARCHIVE_PREFIX}20260101T000000Z.tar.gz"
    own_new = settings.backup_directory / f"{backup._ARCHIVE_PREFIX}20260102T000000Z.tar.gz"
    own_old.write_bytes(b"x")
    own_new.write_bytes(b"x")

    backup._rotate(settings)

    remaining = {p.name for p in settings.backup_directory.iterdir()}
    assert remaining == {other_prefix.name, own_new.name}
