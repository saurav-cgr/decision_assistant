# Install and run

Decision Assistant runs entirely through Docker Compose. No host Python, Node, npm, or PostgreSQL
is required.

## Prerequisites

- Docker Desktop (or Docker Engine + the Compose plugin). No other software.
- A [Gemini API key](https://ai.google.dev/) for the default cloud provider, or a local
  [Ollama](https://ollama.com/) instance for fully offline use (see `docs/providers.md`).

## Hardware

- **Disk**: the built images are roughly 2.6 GB (`api`, which bundles the Docling PDF-parsing and
  OCR models) and 360 MB (`web`), measured from a real build of this repository. Budget several GB
  more for PostgreSQL and uploaded-document data, which grow with your corpus.
- **RAM**: Docling's layout/table models and Tesseract OCR run inside the `api` container and are
  the most memory-hungry part of the stack, particularly when parsing scanned (OCR) PDFs. No
  minimum has been benchmarked yet (tracked as a follow-up); as a starting point, budget at least
  4 GB of RAM available to Docker beyond what PostgreSQL and the OS need, and expect scanned-PDF
  ingestion to use noticeably more than digital-text PDFs of the same page count.
- **Network**: none required at runtime beyond calls to your chosen generation/embedding provider
  (Gemini by default; none at all in Ollama-only offline mode). Docling's own models are downloaded
  once, at image build time, not at runtime — see `AGENTS.md`'s "No runtime downloads" rule.

## Install and start

```bash
make install   # docker compose pull && docker compose build
make start     # docker compose up -d --wait
```

- The web UI becomes available at `http://127.0.0.1:5173` (or whatever port you've configured).
- Only `127.0.0.1` (localhost) port bindings are published for `api`, `web`, and `ollama`;
  PostgreSQL publishes no port at all and is reachable only over the internal Compose network.
  Confirm with `make config` (see below) — there should be no `.:`-style source bind-mounts and no
  non-loopback port bindings.
- The running app version is shown in the UI's account/settings page, and returned by the `/health`
  endpoint's `version` field.

To inspect the resolved Compose configuration without printing secret values (API keys, JWT
signing secret, database password), use `make config`, not bare `docker compose config` — see
`scripts/redact_config.awk`.

## First run

Generate the secrets this install uses — never hand-pick them, and never commit `.env`:

```bash
make setup      # creates .env (mode 600) from .env.example when needed
make start
```

`make setup` generates a fresh `AUTH_JWT_SECRET` and `POSTGRES_PASSWORD`, derives `DATABASE_URL` so
it carries that same password, and then rotates the password on the running database. That last
step is what makes it work on a machine that has started before: the Postgres role's real password
lives in the `postgres_data` named volume from the first boot and does not change just because
`.env` did. Both must match, which is why the command sets them together rather than asking you to.

Re-running is safe: values that are already real are kept, and the command says so. `FORCE=1 make
setup` rotates them instead — that changes the database password, so run it before `make start`.
It never prints a secret value.

One credential it does not create: the login itself. A fresh install has **no user at all**, so the
app asks for one the first time you reach it:

```bash
curl -s http://127.0.0.1:8000/api/v1/setup/status
# {"needs_password_setup":true,"needs_provider_disclosure":true}

curl -s -X POST http://127.0.0.1:8000/api/v1/setup/password \
  -H 'Content-Type: application/json' \
  -d '{"password":"choose-something-long"}'
```

The second call creates the single local user (`decision_assistant`), signs it in, and returns a
**recovery code** — save it, because it is the only way back in if you forget the password. A second
call returns 409 `password_already_set_up`. You do not have to make these calls by hand: the web UI
shows a create-password screen for exactly this state (it asks the server
`GET /api/v1/setup/status` first, so an install that already has a user goes straight to the sign-in
form). `AUTH_BOOTSTRAP_USERNAME`/`AUTH_BOOTSTRAP_PASSWORD` no longer exist — a stale line in `.env`
is ignored, and the app creates no user at startup.

**What these first-run screens are not: access control.** `POST /api/v1/setup/password` has to be
reachable without credentials to work at all — it is safe only because it refuses the second call —
and `POST /api/v1/auth/signup` is also unauthenticated, so an account can be created without ever
visiting the setup screen. `GET /api/v1/setup/status` therefore reports *state* ("no user exists
yet"), not authority. What bounds this stack is the deployment: `api` and `web` publish
`127.0.0.1` only and `db` publishes no port at all (Section 1 above), so nothing off the machine can
reach either endpoint. Do not publish this stack beyond loopback without first deciding what should
happen to `/auth/signup`. The provider-disclosure gate is different in kind: it *is* enforced
server-side, and uploads are refused with 409 `disclosure_not_acknowledged` until acknowledged.

If `AUTH_JWT_SECRET` or `DATABASE_URL` (when it resolves to the shared placeholder credential
above) are missing or invalid, the API container fails to start with a
`ConfigurationError` rather than falling back to a default — this is a deliberate startup guard (not
a bug), added specifically so the app can never silently run on the shared placeholder credential.

**Upgrading an existing install**: `make setup` performs the in-place password rotation for you
(step 4 above). If you would rather do it by hand — or you want to start over instead — run
`make backup` first to save a `decision-assistant-backup-<UTC timestamp>.tar.gz` you can restore
with `make restore -- <backup-file>`, then either reset the volume (destroys all data) or run
`ALTER ROLE` against the live database yourself and update `POSTGRES_PASSWORD`/`DATABASE_URL` in
`.env` to match before the next `make start`.

## Backup and restore

`make backup` writes a timestamped archive of the database and the uploaded documents, and
`make restore -- <backup-file>` puts it back. Both need the stack running, and neither replaces
your `.env`. **Never run `docker compose down -v`** — it deletes the data volumes with no undo.
`docs/backup-restore.md` covers the archive layout, the automatic pre-migration backup, and the
post-restore steps.

## Providers

Gemini is the default for both generation and embedding; Ollama is an optional fully-offline
provider, started behind a Compose profile so `make start` does not touch it. `docs/providers.md`
covers the offline setup, a hardware-suitability check, the switch itself, and what the
provider-disclosure screen reports before your first upload. (The disclosure *gate* is enforced
server-side: uploads are refused with 409 `disclosure_not_acknowledged` until acknowledged.)

## Removing an install

`docs/uninstall.md` lists what lives where (volumes, images, `.env`, `./backups`) and the order to
remove it in, including the one irreversible flag. When something goes wrong instead,
`docs/troubleshooting.md` is the entry point: startup failures, database password mismatches,
rebuilds, provider errors, upload rejections, and the post-restore restart.

## Evaluation (development only)

The evaluation harness is not part of the installed build. Its benchmark lives at
`evaluation/questions.json` in the source tree, which is outside the `api` image's build context,
so `POST /api/v1/workspaces/{id}/evaluations/runs` answers `503` with code
`evaluation_unavailable` against an installed stack. Run evaluation from a source checkout (the
test overlay `compose.test.yml` mounts the repository root read-only) instead.

## Upgrading to a new version

`make start` migrates the schema automatically and rebuilds the corpus when the corpus profiles
changed, while decisions and conversations stay readable throughout. `docs/upgrade.md` covers what
triggers a rebuild, what survives it, how to watch progress, and how to retry one that failed.

## Stopping

```bash
make stop   # docker compose down
```

This does **not** delete your data (documents, decisions, conversations) — those live in named
Docker volumes, not in the containers themselves. Never run `docker compose down -v` unless you
intend to permanently delete everything; run `make backup` first to save a restorable archive
(`make restore -- <backup-file>` to bring it back).
