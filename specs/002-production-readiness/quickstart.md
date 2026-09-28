# Quickstart: Validate Production Readiness

Validation scenarios for the acceptance criteria in `spec.md`. Run in order; each depends on the
previous step's state unless noted.

## Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin) installed — this feature assumes no
  source-mounted dev setup.
- A clean checkout with no `.env` (to exercise first-run secret generation).

## 1. Install and start (User Story 1 / SC-001, SC-002)

```bash
make install   # or: docker compose pull && docker compose build
make start     # or: docker compose up -d --wait
```

- Confirm the web UI loads at `http://127.0.0.1:5173` (or the production port chosen for the
  static build) within ~15 minutes end-to-end on a clean machine.
- Confirm no source directories are bind-mounted: `docker compose config` shows no `.:` volume
  entries for `api`/`web`.
- Confirm binding: `docker compose port db 5432` should fail/be absent; `curl 0.0.0.0:8000/health`
  from another machine on the same network should fail to connect, while `curl
  127.0.0.1:8000/health` from the host succeeds.
- Confirm `/health` response includes a `version` field, and the UI displays it.

## 2. First-run setup (User Story 5 / SC-006)

```bash
make setup                          # generates the secrets; run before the first `make start`
grep -c "AUTH_JWT_SECRET=$" .env                    # expect 0 — value was generated, not left blank
grep -c "decision_assistant:decision_assistant" .env  # expect 0 — password is not the example default
grep -c "AUTH_BOOTSTRAP" .env                       # expect 0 — env bootstrap credentials are gone

make start
curl -s http://127.0.0.1:8000/api/v1/setup/status
# {"needs_password_setup":true,"needs_provider_disclosure":true}

curl -s -X POST http://127.0.0.1:8000/api/v1/setup/password \
  -H 'Content-Type: application/json' -d '{"password":"choose-something-long"}'
# 200 with an access_token, the user, and a recovery_code (save it)

curl -s http://127.0.0.1:8000/api/v1/setup/status
# {"needs_password_setup":false,"needs_provider_disclosure":true}

curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/api/v1/setup/password \
  -H 'Content-Type: application/json' -d '{"password":"a-second-attempt"}'
# 409 — the first-run flow can only create the one user
```

- Confirm `/health` is reachable and reports the version; confirm the API **refuses to start** on a
  placeholder secret (edit `AUTH_JWT_SECRET` back to empty in `.env`, `make start`, expect the
  container to exit with the `ConfigurationError` message, then restore it).
- Note what the password step is **not**: `needs_password_setup` is a state hint, not an
  authorization boundary — `POST /setup/password` is unauthenticated by design and `/auth/signup` is
  open too, so what bounds this flow is that `api`/`web` bind to `127.0.0.1` only (Section 1). The
  disclosure gate below is different in kind: it is enforced server-side, refusing uploads with 409
  `disclosure_not_acknowledged` until acknowledged (DB59, human-decided 2026-09-26).
- Provider disclosure (User Story 6): `GET /api/v1/workspaces/{id}/provider-disclosure` reports what
  the active provider is; `POST .../provider-disclosure/ack` acknowledges it, and until then uploads
  are refused with 409 `disclosure_not_acknowledged`. Both first-run steps also exist as web screens
  (the create-password screen and the disclosure that gates the source library), so this section can
  be walked through either over HTTP or by opening the UI — the commands below are the HTTP half, and
  the checks are the same either way.

## 3. Ingestion survives interruption (User Story 2 / SC-003)

```bash
# start an upload, then kill the API mid-ingestion
docker compose restart api &
# (upload a multi-page document just before/around the restart)
docker compose logs api | grep -i "recover\|requeue"
```

- Confirm the document reaches `succeeded` or a clearly `failed` state (not stuck `processing`)
  within one polling interval after the API comes back, per `GET /documents/{id}`.
- Evaluation runs use the same recovery path, but the evaluation harness is **development only**:
  its benchmark lives at `evaluation/questions.json` in the source tree, outside the `api` image's
  build context, so an installed stack answers `POST /evaluation/runs` with `503` and code
  `evaluation_unavailable`. Verify the evaluation half from a source checkout (the test overlay
  mounts the repo root read-only), not against a released image. See debt DB32.

## 4. Upgrade with corpus rebuild (User Story 3 / SC-004)

```bash
# seed decisions + conversations + ingested documents on the current profile
# change CHUNKING_PROFILE_PRESET (or embedding config) to force corpus_reset_required
docker compose up -d --wait
curl -H "Authorization: Bearer $TOKEN" \
  127.0.0.1:8000/api/v1/workspaces/{id}/corpus-rebuild   # poll until status == completed
# a rebuild that fails on any document aborts whole (DB43): the row reads `failed` with the
# offending document's error code and the previous corpus is left untouched. Retry with
# curl -X POST -H "Authorization: Bearer $TOKEN" \
#   127.0.0.1:8000/api/v1/workspaces/{id}/corpus-rebuild/retry
```

- Throughout the rebuild, confirm `GET /api/v1/workspaces/{id}/decisions` and the conversation
  endpoints (`GET /api/v1/workspaces/{id}/conversations`,
  `GET /api/v1/workspaces/{id}/conversations/{conversation_id}`) keep returning the pre-upgrade
  data (no gap, no error). Only the passage/document-version ids a re-link rewrites and the
  conversation `stale` flag may differ once it finishes.
- Confirm the automatic migration + pre-migration backup both ran (check backup directory for a
  new dump timestamped just before startup).

## 5. Backup and restore (User Story 4 / SC-005)

```bash
make backup    # or scripts/backup.sh <dest-dir>
docker compose down   # NOT -v — data stays in volumes; this only tests the restore path
docker compose up -d --wait
make restore -- <backup-file>   # or scripts/restore.sh <backup-file>
```

- Confirm decisions, conversations, and documents present after restore match the pre-backup
  state.

## 6. Upload safety (User Story 8 / SC-009)

Uploads are workspace-scoped, authenticated, and gated on the provider-disclosure ack, so this section
needs a token, a workspace id, and that ack before it can upload anything. The fixtures are built here
on purpose — the repository ships no "bad" uploads, so none of these commands can go stale. Reach the
timeout case without a genuinely huge PDF by starting the stack with a short parse budget:

```bash
PDF_PARSE_TIMEOUT_SECONDS=1 make start    # one second is far less than Docling needs to load

# The first-run user's name is fixed (auth/bootstrap.py's SETUP_USERNAME) — there is no `admin`.
TOKEN=$(curl -s -X POST 127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"decision_assistant","password":"<the password set in Section 2>"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# A fresh install has no workspace until one is created, so make one and use the id it returns.
WORKSPACE=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Upload safety"}' \
  127.0.0.1:8000/api/v1/workspaces \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

UPLOAD="127.0.0.1:8000/api/v1/workspaces/$WORKSPACE/documents/upload"
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "127.0.0.1:8000/api/v1/workspaces/$WORKSPACE/provider-disclosure/ack"

printf 'this is not a pdf' > /tmp/not-a-pdf.pdf
head -c 30000000 /dev/urandom > /tmp/oversized.pdf

curl -s -F "files=@/tmp/not-a-pdf.pdf;filename=fake.pdf" -H "Authorization: Bearer $TOKEN" "$UPLOAD"
# content_type_mismatch — the bytes do not match the .pdf suffix
curl -s -F "files=@/tmp/oversized.pdf" -H "Authorization: Bearer $TOKEN" "$UPLOAD"
# file_too_large — larger than MAX_UPLOAD_BYTES (25 MiB by default)
curl -s -F "files=@api/tests/fixtures/pdf/digital-english.pdf" -H "Authorization: Bearer $TOKEN" "$UPLOAD"
# pdf_parse_timeout — a real PDF against the 1 s budget
curl -s -F "files=@api/tests/fixtures/meeting.md;type=text/markdown" -H "Authorization: Bearer $TOKEN" "$UPLOAD"
# accepted; poll GET .../documents until that document reads `completed`
```

The `;type=text/markdown` matters: curl defaults a `.md` upload to `application/octet-stream`, which
`_validate_file` refuses with `unsupported_media_type` before the bytes are ever read.

- Each rejection carries its own code, and the job-level ones (`content_type_mismatch`,
  `pdf_parse_timeout`) also carry `retryable: false`. The upload-level `file_too_large` refusal
  happens before an ingestion job exists, so it returns `code` and `message` only. The last upload
  still completes, so a rejected or timed-out file does not wedge the worker (FR-022).
- Confirm the timed-out parse did **not** outlive its job: `docker compose stats --no-stream api`
  right after the timeout should show the API back at idle rather than holding several cores and
  gigabytes (DB60/V139 — the parse runs in a child process that the timeout kills). The shipped
  fixtures are single-page, so at a 1 s budget the child dies before Docling has allocated much and
  the reclaim will be small; to actually watch it, use your own page-heavy PDF (roughly 20–100 pages)
  with `PDF_PARSE_TIMEOUT_SECONDS=25 make start`.
- `pdf_page_limit_exceeded` needs a PDF with more than `MAX_PDF_PAGES` pages (200 by default); the
  check runs before the parser, so any page-heavy PDF shows it.
- Re-run the last two uploads with the normal budget (`make stop && make start`) and the real PDF
  completes instead of timing out.

## 7. Diagnostics bundle (User Story 7 / SC-008)

```bash
curl -s -o /tmp/bundle.zip -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  127.0.0.1:8000/api/v1/diagnostics/bundle     # 200 with the token; 401 without one or with a bad one
unzip -l /tmp/bundle.zip                       # settings.json, alembic-current.txt, version.txt, logs/
unzip -p /tmp/bundle.zip settings.json | grep -iE 'GEMINI_API_KEY|AUTH_JWT_SECRET|PASSWORD'
# expect no matches — settings.json is an allowlist, and it must not carry a credential

# Read the configured values out of .env rather than expanding a shell variable: an unset
# `$GEMINI_API_KEY` expands to the empty string, and `grep -F ""` matches every line, which reads
# as a leak. `sed -n 's/^KEY=//p' | tail -n 1` mirrors how Compose reads the last value.
DB_PASSWORD=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env | tail -n 1)
JWT_SECRET=$(sed -n 's/^AUTH_JWT_SECRET=//p' .env | tail -n 1)
API_KEY=$(sed -n 's/^GEMINI_API_KEY=//p' .env | tail -n 1)
BUNDLE_DIR=$(mktemp -d)
unzip -q /tmp/bundle.zip -d "$BUNDLE_DIR"
for secret in "$DB_PASSWORD" "$JWT_SECRET" "$API_KEY"; do
  [ -n "$secret" ] || continue
  grep -rIF "$secret" "$BUNDLE_DIR" && echo "LEAK: a configured secret value is in the bundle"
done
# expect no matches from any grep above
```

- Grep for **encoded and derived** secret forms as well as the raw values (DB56): the percent-encoded
  database password (`python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' '<password>'`),
  the base64 of the API key, and any URL that carries credentials (`OLLAMA_BASE_URL` userinfo).
  Scrubbing since DB56 covers those forms too (each secret is redacted raw, percent-encoded, base64,
  and as `user:password` userinfo), so this grep is an independent check of that claim, not a known
  gap.
- `settings.json` is the allowlisted subset of `Settings` — provider names, model names, limits. It
  must not contain `DATABASE_URL`, `AUTH_JWT_SECRET`, or the API key.

## 8. CI (SC — process, not runtime)

- Open a PR; confirm the GitHub Actions workflow runs lint, typecheck, `make test-api`,
  `make test-web`, and a fresh-DB migration check, and that a release tag triggers the image build
  and gitleaks scan.
