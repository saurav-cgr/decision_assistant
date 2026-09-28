# Model providers

This install talks to two independent providers:

- a **generation provider**, which turns retrieved evidence into an answer, and
- an **embedding provider**, which turns document text into the vectors the search index is built
  from.

They are chosen separately, and the default for both is Gemini. Only the embedding side is part of
the corpus profile, so it is the side that can force a re-index — see
[Switching providers](#switching-providers) below.

## Default: Gemini (document text leaves this machine)

`.env` ships with:

```dotenv
GENERATION_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=
```

Set `GEMINI_API_KEY` to a real key and run `make start`. The first-run disclosure screen (and
`GET /api/v1/workspaces/{id}/provider-disclosure`) reports that document text leaves the machine in
this configuration, and uploads are refused until that disclosure is acknowledged.

Which models are used is set by `GEMINI_GENERATION_MODEL`, `GEMINI_EMBEDDING_MODEL` and
`GEMINI_EMBEDDING_DIMENSION`. Changing the embedding **model** or **dimension** changes the corpus
profile and triggers a rebuild; changing only `GEMINI_GENERATION_MODEL` does not.

## Fully offline: Ollama

Ollama runs as a Compose service behind a profile (`compose.yaml`, service `ollama`), so it is an
explicit opt-in and **not** started by `make start`.

### 1. Start the service and pull the models

```bash
docker compose --profile ollama up -d ollama --wait

docker compose --profile ollama exec -T ollama ollama pull qwen3:8b
docker compose --profile ollama exec -T ollama ollama pull embeddinggemma

docker compose --profile ollama exec -T ollama ollama list   # both should be listed
```

Those two names are `.env.example`'s defaults. If you changed `OLLAMA_GENERATION_MODEL` or
`OLLAMA_EMBEDDING_MODEL`, pull the names you set instead — the commands are literal on purpose,
because a shell `${OLLAMA_GENERATION_MODEL:-...}` would fall back to the default rather than read
your `.env`.

The image tag is pinned in `compose.yaml` (`ollama/ollama:0.5.7` when this was written). A model
name newer than that image will fail to pull — bump the tag in `compose.yaml`, then re-run the
commands above.

Models are stored in the `ollama_data` volume, so they survive `make stop` and container rebuilds.
They do **not** survive `docker compose down -v`.

### 2. Point the app at it

In `.env`:

```dotenv
GENERATION_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_GENERATION_MODEL=qwen3:8b
OLLAMA_EMBEDDING_MODEL=embeddinggemma
OLLAMA_EMBEDDING_DIMENSION=768
```

`OLLAMA_BASE_URL` uses the Compose service name, not `localhost`: it is resolved inside the Compose
network by the `api` container. If you run Ollama on the host instead of as a Compose service, this
becomes `http://host.docker.internal:11434` on Docker Desktop.

Then:

```bash
make start      # no --profile needed: only the api/web/db services are started
```

Because both providers are now `ollama`, the disclosure screen reports that document text stays on
this machine. You can leave `GEMINI_API_KEY` empty — nothing will call it.

### 3. Confirm nothing is sent out

- `docker compose --profile ollama logs ollama` shows the model requests; there is no second client.
- With no `GEMINI_API_KEY` set and both providers set to `ollama`, the API cannot construct a Gemini
  client at all (see `providers/factory.py`) — an offline install has no cloud credential to leak.

A caution worth stating plainly: the disclosure treats **any** provider name it does not recognise as
remote. Setting `EMBEDDING_PROVIDER`/`GENERATION_PROVIDER` to an invented value does not create an
offline mode; the app falls back to the Ollama client implementation but still reports "text leaves
this machine".

## Hardware suitability (FR-015)

There is no benchmarked minimum (see `docs/install.md`'s Hardware section for the stack as a whole).
What matters for an offline install is that the generation model fits in memory the machine can
spare, and that answers come back fast enough to be usable.

As a rule of thumb, a 4-bit-quantized model needs roughly 1 GB of RAM or VRAM per billion
parameters:

| Model | Rough footprint | Notes |
|-------|-----------------|-------|
| `embeddinggemma` (embedding) | well under 1 GB | Small and cheap; needed on the ingestion path. |
| `qwen3:8b` (generation) | ~6 GB | The dominant cost. |

Add the Docker VM's own overhead plus the `api` container's Docling models (see `docs/install.md`)
and budget the total for the machine. A 16 GB machine is comfortable; 8 GB is workable but tight
while a large PDF is also being parsed. With no GPU, Ollama runs on CPU: it works, but expect
answers to take tens of seconds.

Measure it on your own hardware rather than trusting the table:

```bash
# Read the configured model out of .env rather than expanding a shell variable, which would
# silently fall back to the default instead of reading the file.
GEN_MODEL=$(sed -n 's/^OLLAMA_GENERATION_MODEL=//p' .env | tail -n 1)

# Time a trivial generation through the model you actually configured.
time docker compose --profile ollama exec -T ollama \
  ollama run "$GEN_MODEL" "Reply with the single word: ready"

# Is it on a GPU, or on CPU? And what is it using right now?
docker compose --profile ollama exec -T ollama ollama ps
docker stats --no-stream
```

If latency is unacceptable, a smaller generation model is the lever — it does not affect the corpus
profile, so it needs no re-index when you change it.

## Switching providers

Two ways, same endpoint underneath:

- **Web UI**: Account → *Model provider*. Choosing a provider only changes what the next request
  uses; a change that alters the embedding profile opens a confirmation dialog first, because every
  document in every workspace has to be indexed again.
- **HTTP**: `POST /api/v1/workspaces/{id}/provider` with
  `{"generation_provider": "ollama", "embedding_provider": "ollama", "confirm_rebuild": false}`.
  A profile-changing switch answers `409 provider_switch_requires_rebuild` with a preview
  (`documents_total`, `workspaces` — each workspace's name and count — current and proposed embedding
  profiles, and `disclosure_acknowledgement_will_be_cleared`) and has no side effects; resubmit the
  same body with `"confirm_rebuild": true` to proceed (`202`, with the dispatched rebuild).

Errors you can expect instead of a silent failure:

| Code | Meaning |
|------|---------|
| `provider_switch_requires_rebuild` | The embedding profile changes; confirm with `confirm_rebuild: true`. |
| `provider_switch_not_configured` | The target provider's credentials are missing locally (for Gemini, `GEMINI_API_KEY`). Nothing was written. |
| `corpus_rebuild_in_progress` | A rebuild is already pending or running for some workspace in this installation (the provider choice is process-wide). Wait for it, or retry it if it failed. |
| `provider_authentication_failed` / `provider_configuration_invalid` | The provider rejected the key or the configuration. |
| `provider_unavailable` | The provider could not be reached (most often: the `ollama` service is not running). |

A switch is persisted in the `app_settings` table and applied in-process, so it takes effect for the
running API without a restart. `GENERATION_PROVIDER`/`EMBEDDING_PROVIDER` in `.env` remain the
startup defaults — a restart re-applies the stored choice over them. `docs/upgrade.md` covers what a
rebuild does and how to watch its progress.

### Known limits

- **The disclosure names both providers, but not the profile a switch would change to.** `GET
  .../provider-disclosure` returns the active generation and embedding providers plus which of them
  sends text off the machine, so the settings form pre-fills both selects from it. It does not report
  the embedding *profile* (model/version) ahead of a switch, so the confirmation dialog's proposed
  profile still comes from the 409 payload.
- **The stored choice is one row for the whole process, while the switch route is per workspace**
  (DB57). The switch is now refused while any workspace has a rebuild pending or running
  (`corpus_rebuild_in_progress`), and the 409 preview lists every workspace with its document count
  instead of only the addressed one. Two residuals remain: the switch dispatches a rebuild for the
  addressed workspace only, and the others re-ingest themselves through the `corpus_reset_required`
  path on their next readiness check — a restart is the quickest way to run that check for all of
  them at once.
- **A local-to-remote switch clears the data-handling acknowledgement** (DB65). When a switch makes
  any provider start sending document text off the machine, every workspace's
  `disclosure_acknowledged_at` is reset; uploads stay blocked with `disclosure_not_acknowledged` until
  each workspace is acknowledged again. The 409 preview reports this as
  `disclosure_acknowledgement_will_be_cleared`, and a confirmed switch answers
  `disclosure_acknowledgement_cleared: true`.
- **A switch to an unreachable provider still succeeds.** Configuration presence is validated, not
  reachability, so switching to Ollama before starting the service persists the change and only fails
  later, per request, with `provider_unavailable`.
