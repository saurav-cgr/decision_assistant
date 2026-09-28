# Troubleshooting

Start with the evidence, not with a guess:

```bash
make logs                                        # docker compose logs -f (all services)
docker compose logs --tail=200 api               # just the API, if `make logs` is noisy
docker compose ps                                # which services are up, and are they healthy?
make config                                      # resolved compose config, secrets redacted
```

For anything the API itself is doing, Account → **Download diagnostics bundle** (or
`GET /api/v1/diagnostics/bundle`) returns a zip with `settings.json` (the allowlisted
configuration), `alembic-current.txt` (the DB revision), `version.txt` and the application logs. It
contains no secret values, which is what makes it safe to attach to a report. The logs live on the
`api_logs` volume, so they survive a container recreate (`make start` after a config change, or an
image upgrade); the route itself needs the database, so it cannot be downloaded while Postgres is
down.

## The API container exits (or restarts in a loop)

`make start` waits for health checks, so a startup failure looks like a hang. Look at the logs:

```bash
docker compose logs --tail=50 api
```

The most common cause is a `ConfigurationError`, which aborts startup **on purpose** rather than
falling back to a default:

| Message | Cause | Fix |
| --- | --- | --- |
| `AUTH_JWT_SECRET is not configured` | `.env` has no real JWT secret | `make setup`, then `make start` |
| `DATABASE_URL is using the shared placeholder credential` | `.env` still points at `decision_assistant:decision_assistant` | `make setup` (it generates the password and rewrites `DATABASE_URL`) |

`api` has `restart: unless-stopped`, so a misconfigured container comes back and fails again instead
of staying down — a repeating log is the normal shape of this failure, not a second bug.

## `make start` never becomes healthy

- `docker compose ps` shows which service is unhealthy. `db` failing its health check is usually a
  password mismatch (below); `web` waits for `api`, and `api` waits for `db`.
- A port collision looks different: `make start` fails fast with "port is already allocated". Check
  `API_PORT`, `WEB_PORT` and `OLLAMA_PORT` in `.env` against what is already listening.
- On a first start, `api` also runs migrations and (when a migration is pending) takes a pre-migration
  backup, so allow a few seconds before deciding it is stuck.

## The database password does not match

Postgres sets the role's password from `POSTGRES_PASSWORD` **once**, when it initialises an empty
`postgres_data` volume. Editing `POSTGRES_PASSWORD` in `.env` afterwards changes what the API tries to
use but not what the database accepts, so the API fails to connect.

```bash
make setup            # re-derives DATABASE_URL and rotates the role over the live database
make start
```

`FORCE=1 make setup` rotates the generated secrets as well (including `AUTH_JWT_SECRET`, which signs
existing tokens out). Both are safe to run; neither prints a secret.

## Corpus rebuild

After an upgrade — or a provider switch that changes the embedding profile — the API reports
`corpus_reset_required` on `/ready` and starts a rebuild that re-ingests every document. Documents go
stale, decisions and conversations stay readable. See `docs/upgrade.md` for the full model.

- **Watch it**: `GET /api/v1/workspaces/{id}/corpus-rebuild`, or the banner on the Workspace page.
- **It failed**: the row reads `failed` with the offending document's error code, and the previous
  corpus was left untouched (a failed rebuild aborts whole rather than half-applying). Fix the cause,
  then `POST /api/v1/workspaces/{id}/corpus-rebuild/retry` — or the banner's **Retry rebuild**.
- **`409 corpus_rebuild_not_retryable`**: retry is only accepted while the latest attempt is `failed`
  and no other rebuild is active.
- **A rebuild that never finishes after a crash** is swept to `failed` on the next API start, so it
  can be retried rather than blocking later rebuilds.

## Provider failures

These surface in the UI with a specific message (not a generic error), and every one is also an HTTP
error code. The codes and their fixes:

| Code | What it means | Fix |
| --- | --- | --- |
| `provider_authentication_failed` | The provider rejected the API key | Set a valid `GEMINI_API_KEY` in `.env`, `make start` |
| `provider_configuration_invalid` | The provider is not configured | Fill in the key or base URL in `.env`, `make start` |
| `provider_unavailable` | The provider cannot be reached | For Ollama: is the service up? See below |
| `provider_quota_exhausted` | The provider account is out of quota | Restore quota in the provider account |
| `provider_rate_limited` | Too many requests | Wait and retry |
| `provider_switch_not_configured` | You switched to a provider with no local credentials | Configure it first (`docs/providers.md`) |
| `corpus_rebuild_in_progress` | A switch was attempted while a rebuild is pending or running for some workspace | Wait for it, or retry it if it failed |

**Ollama-specific**: the `ollama` service is behind a Compose profile, so `make start` does **not**
start it.

```bash
docker compose --profile ollama up -d ollama --wait
docker compose --profile ollama exec -T ollama ollama list    # are the models pulled?
```

`OLLAMA_BASE_URL` must be `http://ollama:11434` when Ollama runs as a Compose service (the name is
resolved inside the Compose network, not on the host), or `http://host.docker.internal:11434` when it
runs on the host. A switch to an unreachable provider still succeeds — reachability is not validated
at switch time — so a `provider_unavailable` after a switch points at the service, not the setting.
See `docs/providers.md`.

## Uploads are rejected

Every rejection carries its own code and `retryable: false`, and the worker stays available for the
next upload (FR-022).

| Code | Cause | Fix |
| --- | --- | --- |
| `disclosure_not_acknowledged` | The provider disclosure was never acknowledged | Open the Workspace page and acknowledge, or `POST /api/v1/workspaces/{id}/provider-disclosure/ack` |
| `unsupported_file_type` | Not `.md`, `.txt`, `.pdf` or `.docx` | Convert the file |
| `unsupported_media_type` | The declared media type disagrees with the extension — `curl` sends `application/octet-stream` by default | Send an explicit type: `-F "files=@notes.md;type=text/markdown"` |
| `content_type_mismatch` | The file's bytes disagree with its extension (a `.pdf` that is not a PDF) | Re-export the file |
| `file_too_large` | Over `MAX_UPLOAD_BYTES` (25 MiB by default) | Raise the limit in `.env`, or split the document |
| `pdf_page_limit_exceeded` | Over the 200-page limit (`max_pdf_pages`) | Split the PDF; the check runs before parsing |
| `pdf_parse_timeout` | Either the parse exceeded `PDF_PARSE_TIMEOUT_SECONDS` (120 by default), or the document waited longer than `max(600 s, 20 x that budget)` for a free parse slot (`PDF_PARSE_CONCURRENCY`, default 1) | Raise the budget for large documents; the timed-out parse is killed in a child process, so nothing is left burning CPU. A PDF that fails this way without its own parse ever starting was queued behind other PDFs — unblock the queue, or raise `PDF_PARSE_TIMEOUT_SECONDS` (the queue cap scales with it) |
| `pdf_no_extractable_text` | A PDF with no text layer | It needs OCR; scanned PDFs are OCR'd, an image-only page region may still come up empty |

`GET /api/v1/workspaces/{id}/documents` reports each document's status, stage, progress and error
code; failed documents expose a retry (`POST .../documents/{id}/retry`) when the failure is
retryable, which the UI shows as a **Retry** button.

## The first request after a restore fails

A restore drops and recreates tables while the API holds pooled connections to the old schema, so
the next request can fail with a stale connection or type error before recovering (DB51).

`make restore` / `scripts/restore.sh` already handle it: when the API is running they restart the
container and wait for its healthcheck before printing `Restore complete.`, which drops the pooled
connections and their cached statement plans. If you restored the database by hand instead, do the
same:

```bash
docker compose restart api && docker compose up -d api --wait
```

See `docs/backup-restore.md` — including why the uploads volume can contain files the database does
not reference after a restore.

## Evaluation answers `503 evaluation_unavailable`

Expected against an installed stack. The benchmark lives at `evaluation/questions.json` in the source
tree, outside the `api` image's build context, so evaluation is a **development-only** surface. Run
it from a source checkout with the test overlay, not against a released image. Do not "fix" this by
adding a source bind-mount.

## Disk growing, or the API killed while parsing many PDFs

- `docker system df` shows what Docker is holding. Build cache and dangling images are the usual
  culprits; `docker image rm` the unused ones. Do **never** use `docker system prune --volumes` —
  it deletes volumes, including `postgres_data`.
- Docling parses PDFs in a killable child process, capped process-wide by `PDF_PARSE_CONCURRENCY`
  (default 1, the memory bound). Raising it lets more parses run at once and raises peak memory; the
  `api` service has `restart: unless-stopped` so it comes back on its own if it is ever killed, but
  the ingestion job that was in flight is retried rather than resumed.
- Logs live on the `api_logs` volume, so they survive a container recreate; the file itself rotates
  at 5 MB with 3 backups kept.

## Nothing here matches

Collect the diagnostics bundle and the redacted config, then check `docs/install.md`,
`docs/providers.md`, `docs/upgrade.md` and `docs/backup-restore.md`. For a development checkout,
`make lint-api`, `make test-api` and `make test-web` run the same gates as CI (`AGENTS.md` documents
the exact commands, including the `-p` project isolation they rely on).
