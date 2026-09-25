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

On first start, the app generates its own local secrets and prompts you to set an admin password —
no shared default credentials exist anywhere in this project. See `docs/providers.md` for choosing
between the default cloud provider (Gemini) and fully offline (Ollama) operation, and the
first-run privacy disclosure it shows either way.

## Stopping

```bash
make stop   # docker compose down
```

This does **not** delete your data (documents, decisions, conversations) — those live in named
Docker volumes, not in the containers themselves. Never run `docker compose down -v` unless you
intend to permanently delete everything; see `docs/backup-restore.md` for backing up first.
