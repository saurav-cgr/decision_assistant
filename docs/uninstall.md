# Uninstall

There is no uninstall script: everything an install creates lives in Docker (containers, images and
named volumes) plus two paths on the host (`.env` and the backup directory). This page is the order
to remove them in, and what each step destroys.

Read [What is where](#what-is-where) first — the difference between "stop", "remove the software" and
"delete the data" is entirely the `-v` flag and which volumes you name.

## What is where

| Artifact | Where | Removed by |
| --- | --- | --- |
| Containers (`api`, `web`, `db`, optionally `ollama`) | Docker | `make stop`, or `docker compose down` |
| Database, uploaded documents | volumes `decision-assistant_postgres_data`, `decision-assistant_uploads_data` | `docker compose down -v`, or `docker volume rm` |
| Application logs | volume `decision-assistant_api_logs` | same |
| Ollama models | volume `decision-assistant_ollama_data` | same |
| Images | Docker image store (`decision-assistant-api`, `decision-assistant-web`) | `docker image rm` |
| Generated secrets and configuration | `.env` in the checkout | you |
| Backups | `./backups` (or `BACKUP_DIR`), on the host | you |

Run `docker volume ls | grep decision` to see which of these exist on your machine.

## 1. Stop the stack (keeps all data)

```bash
make stop          # docker compose down — containers go, volumes stay
```

This is the reversible step: `make start` brings everything back with your decisions, conversations
and documents intact.

If you enabled the offline provider, stop it too:

```bash
docker compose --profile ollama down
```

## 2. Remove the software (keeps all data)

```bash
make stop
docker image rm decision-assistant-api:latest decision-assistant-web:latest
```

Reclaiming the space is worth it here: `decision-assistant-api` bundles the Docling PDF-parsing and
OCR models and is the largest image in the install (see `docs/install.md`). `make install` rebuilds
both images from source.

## 3. Before deleting data: take a backup

```bash
make backup      # writes ./backups/decision-assistant-backup-<UTC timestamp>.tar.gz
```

`make restore -- <backup-file>` brings a stack back from that archive, and the archive is readable
without this repository — it is a `pg_dump` plus a tar of the uploads volume. **`.env` is not in the
archive**, and the generated secrets in it are what make a restored database usable, so keep a copy
of `.env` alongside the archive.

## 4. Delete the data (irreversible)

> **Warning**
>
> The next commands permanently delete every decision, conversation, document and Ollama model
> download. There is no undo and no automatic backup of a volume deletion. Do step 3 first.

```bash
make stop
docker compose down -v        # removes the project's containers and named volumes
```

If you only want to delete data and keep the images for a later `make start`, that is still the
command — `make start` recreates containers and volumes as needed.

To remove one volume at a time instead (for example, to drop the Ollama model downloads but keep
your documents), name them explicitly:

```bash
docker volume rm decision-assistant_ollama_data
docker volume rm decision-assistant_postgres_data decision-assistant_uploads_data
docker volume rm decision-assistant_api_logs
```
Never use `docker system prune --volumes` or delete the Docker Desktop disk image for this: both
take unrelated projects' data with them.

## 5. Remove the host files

In the checkout (or wherever you cloned it):

- `.env` — the generated `AUTH_JWT_SECRET`, `POSTGRES_PASSWORD` and `DATABASE_URL`. Delete it if you
  are finished with this install; keep it with your backup if you might restore.
- `./backups` — your archives. Delete only when you no longer want to restore.

```bash
rm -f .env
rm -rf ./backups        # only if you no longer want a restore path
```

## Starting over instead of uninstalling

If the goal is a fresh install rather than removal — for example after a corpus-profile change —
you do not need any of the above: `docs/upgrade.md` covers the supported rebuild path, and the
development-only corpus reset in `AGENTS.md` drops and recreates just the PostgreSQL database inside
the existing volume.
