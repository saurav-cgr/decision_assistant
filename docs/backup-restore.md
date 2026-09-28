# Backing up and restoring Decision Assistant

Two commands cover the whole lifecycle:

```bash
make backup                          # write a new archive
make restore -- <backup-file>        # restore that archive
```

Both delegate to `scripts/backup.sh` and `scripts/restore.sh`, so you can also call the scripts
directly (`scripts/backup.sh <dest-dir>`, `scripts/restore.sh <backup-file>`) from a checkout.

An archive captures everything the application stores in PostgreSQL — workspaces, documents and
their versions, passages, ingestion jobs, decisions and their evidence, conversations, question
history, evaluation runs — plus every uploaded file. It does **not** capture your `.env` file,
Docker images, or the Ollama model data, so keep a copy of `.env` somewhere safe; the generated
secrets in it are what make a restored database usable.

## Before you delete anything: do not use `down -v`

> **Warning**
>
> `docker compose down -v` permanently deletes the project's named volumes, including
> `postgres_data` (every decision, conversation, and document) and `uploads_data`. There is no
> undo and no automatic backup of a volume deletion. Run `make backup` first, and prefer plain
> `make stop` (`docker compose down`, no `-v`), which stops the stack and keeps all data.

The same warning applies to `docker volume rm`, `docker system prune --volumes`, and deleting the
Docker Desktop disk image. The one destructive workflow this project documents (resetting the
corpus for a new chunking/embedding profile) drops and recreates only the PostgreSQL *database*
inside the existing volume — it never removes a volume. See `docs/upgrade.md`.

## Making a backup

```bash
make backup                        # default destination: ./backups
make backup BACKUP_DIR=/path/to/backups
```

The stack must be running (`make start`), because the script runs `pg_dump` inside the `db`
service and tars the uploads volume through the `api` service.

The command prints the path it wrote, for example
`backups/decision-assistant-backup-20260926T101500Z.tar.gz`. The archive contains exactly two
members:

| Member | Contents |
| --- | --- |
| `database.sql` | `pg_dump --clean --if-exists` of the whole database |
| `uploads.tar` | the contents of the `uploads_data` volume |

`--clean --if-exists` makes the dump self-dropping, so restoring it over a populated database
replaces rows instead of failing on already-existing tables.

`backups/` is gitignored. Keep archives outside the Docker volumes (the default location already
is) so a volume deletion cannot take them with it.

## Restoring a backup

```bash
make stop                     # optional but recommended: quiesce the stack first
make start
make restore -- backups/decision-assistant-backup-20260926T101500Z.tar.gz
```

`make restore` takes the file after `--`. With no argument it prints
`Usage: make restore -- <backup-file>` and exits non-zero. The restore runs the dump with
`psql -v ON_ERROR_STOP=1`, so a broken dump fails loudly instead of partially applying.

To verify a backup/restore pair without touching your real stack, run the automated round trip:

```bash
make test-backup
```

It seeds an isolated project, runs `scripts/backup.sh`, wipes the data, runs
`scripts/restore.sh`, and compares row counts and upload files.

### After a restore

- **The API is restarted for you.** The restore drops and recreates tables while the API holds
  pooled connections to the old schema, so its first request could fail on a stale statement plan
  or type OID (DB51). `scripts/restore.sh` restarts the `api` service at the end when it is running,
  which drops the pool; a restore against a stopped stack does not restart anything.
- **The uploads directory matches the archive.** `scripts/restore.sh` clears `/workspace/uploads`
  before extracting `uploads.tar`, so files uploaded after the backup do not survive the restore.
- **The scripts read `POSTGRES_USER`/`POSTGRES_DB` from `.env` first** (then from the shell
  environment, then their shipped defaults). A customized `.env` needs no extra flags, but an
  explicit environment value still wins:

  ```bash
  POSTGRES_USER=myuser POSTGRES_DB=mydb make backup
  ```

- **A restore does not migrate.** If the archive came from an older version, the next `make start`
  applies pending migrations automatically (and takes its own pre-migration backup first).

## Automatic pre-migration backups

Startup takes its own backup before applying pending schema migrations (FR-005). It is written to
the API container's `/workspace/backups` — the host's `./backups` by default, or whatever
`BACKUP_DIR` in `.env` points at — as
`decision-assistant-premigration-backup-<UTC timestamp>.tar.gz`, with the same
`database.sql` + `uploads.tar` layout, so `make restore -- <that file>` works on it too.

These are separate from `make backup` archives and rotate on their own: the newest
`PRE_MIGRATION_BACKUP_RETENTION` (default 5) are kept, and user-triggered backups are never
touched. A backup is only taken when a migration is actually pending, and if it fails, startup
aborts before migrating. See `docs/upgrade.md` for the full startup sequence.
