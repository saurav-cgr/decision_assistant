import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from decision_assistant.config import Settings

_ARCHIVE_PREFIX = "decision-assistant-premigration-backup-"


class PreMigrationBackupFailed(Exception):
    """Raised when the automatic pre-migration backup could not be produced.

    FR-005 requires a backup before applying pending migrations; callers
    should let this propagate rather than proceeding to migrate without one.
    """


def _pg_dump_url(database_url: str) -> str:
    # pg_dump expects a plain libpq `postgresql://` URI; `+asyncpg` is a
    # SQLAlchemy driver suffix pg_dump doesn't understand.
    prefix = "postgresql+asyncpg://"
    if database_url.startswith(prefix):
        return "postgresql://" + database_url[len(prefix) :]
    return database_url


def create_pre_migration_backup(settings: Settings) -> Path:
    """Dump the database and archive uploads before an automatic migration.

    Produces `<backup_directory>/decision-assistant-premigration-backup-<UTC
    timestamp>.tar.gz`, matching scripts/backup.sh's internal layout
    (`database.sql` plus a nested `uploads.tar`) so scripts/restore.sh can
    read either archive. Kept under a distinct filename prefix so rotation
    here never touches user-triggered backups from `make backup`.

    Synchronous and blocking (shells out to `pg_dump`); callers inside an
    event loop must invoke this via a worker thread (e.g. `asyncio.to_thread`).
    """
    settings.backup_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = settings.backup_directory / f"{_ARCHIVE_PREFIX}{timestamp}.tar.gz"
    dump_path = settings.backup_directory / f".{_ARCHIVE_PREFIX}{timestamp}.sql"
    uploads_tar_path = settings.backup_directory / f".{_ARCHIVE_PREFIX}{timestamp}-uploads.tar"
    try:
        with dump_path.open("wb") as dump_file:
            result = subprocess.run(
                ["pg_dump", "--clean", "--if-exists", _pg_dump_url(settings.database_url)],
                stdout=dump_file,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            raise PreMigrationBackupFailed(
                f"pg_dump exited {result.returncode}: "
                f"{result.stderr.decode(errors='replace')}"
            )

        with tarfile.open(uploads_tar_path, "w") as uploads_tar:
            for entry in sorted(settings.upload_directory.iterdir()):
                uploads_tar.add(entry, arcname=entry.name)

        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(dump_path, arcname="database.sql")
            archive.add(uploads_tar_path, arcname="uploads.tar")
    finally:
        dump_path.unlink(missing_ok=True)
        uploads_tar_path.unlink(missing_ok=True)

    _rotate(settings)
    return archive_path


def _rotate(settings: Settings) -> None:
    backups = sorted(settings.backup_directory.glob(f"{_ARCHIVE_PREFIX}*.tar.gz"))
    excess = len(backups) - settings.pre_migration_backup_retention
    for stale in backups[: max(excess, 0)]:
        stale.unlink(missing_ok=True)
