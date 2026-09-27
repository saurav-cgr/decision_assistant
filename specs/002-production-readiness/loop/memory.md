# Loop Memory

Conventions, decisions, and dead ends that should survive between runs so the
loop never re-derives or re-litigates them. Keep entries short and durable.

- [M-001] `api/Dockerfile` uses a multi-stage build: `base` (production, `pip install .`, no
  `[dev]` extras — this is the image shipped/published) and `test` (`FROM base`, adds `[dev]`
  extras — this is what `make test-api` / CI must build and run against). Do not collapse back to
  a single editable-install stage; `make test-api` runs `docker compose run --rm api pytest`,
  which needs pytest available without shipping it in production. (decided during
  `/speckit-implement` T001, 2026-09-24)
- [M-002] Corpus reset for the automatic upgrade-rebuild path (US3) must be a *scoped* truncate of
  corpus-derived tables only (`documents, document_versions, passages, embedding_cache,
  ingestion_jobs, retrieval_traces`), never the full `dropdb`/`createdb` sequence in AGENTS.md —
  that sequence destroys `decisions`/`conversations` too and remains a human-invoked
  development-only fallback, not something the automatic rebuild calls. (research.md R5)
- [M-003] `IngestionJob` table and a `recover_stale_jobs()` function already exist in
  `api/src/decision_assistant/ingestion/jobs.py` but are dead code (never called). US2's job
  recovery work extends and wires this existing function rather than building new infrastructure
  from scratch — check it's not accidentally duplicated.
- [M-004] `docker compose config` (no args) prints resolved env values inline, including secrets
  from local `.env` (`AUTH_JWT_SECRET`, `GEMINI_API_KEY`, `AUTH_BOOTSTRAP_PASSWORD`, etc). Never
  run it unfiltered where output lands in a shared log/ticket/transcript — pipe through
  `grep`/`sed` for only the fields being checked (ports, volumes, image tags). (found iteration 6)
- [M-005] Per-iteration worktree branches (`loop-iter-N`) are not auto-merged into `improvement`;
  they pile up until a human explicitly asks for reconciliation (this happened at iteration 6,
  merging loop-iter-2..5 with `git merge --no-ff` in task order, one at a time, deleting the
  worktree/branch after each merges cleanly). Until asked, do not merge on your own initiative —
  but do expect compose.yaml-touching tasks (multiple iterations edited it) to conflict at merge
  time and require manual resolution, not just `git merge -X ours/theirs`.
- [M-006] This sandbox's Docker network cannot reach Docker Hub to pull base-image layers/metadata
  (`docker compose build`/`up` fail with `DeadlineExceeded`). `docker manifest inspect` against a
  registry DOES work (used to verify the ollama tag at iteration 4/checker V3). So: registry
  metadata lookups are possible, full image builds/runs are not — plan verification accordingly,
  don't keep re-attempting a live build expecting a different result.
- [M-007] Vite bakes `import.meta.env.*` (e.g. `VITE_API_URL`) into the JS bundle at `npm run
  build` time. Once `web/Dockerfile` moved to a multi-stage build with a prebuilt static `dist/`
  served by nginx (T002), any `environment:` entry for a `VITE_*` var in compose.yaml has zero
  effect at container runtime — it would need to become a Docker build ARG instead. Don't assume
  compose `environment:` blocks configure a Vite-built static frontend the way they'd configure a
  dev server or a backend process. (found iteration 8, tracked as DB6)
- [M-009] "Image builds successfully" is not sufficient verification for `api/Dockerfile` — it
  must also actually run migrations. T001's rewrite silently dropped `alembic/`/`alembic.ini`
  from the image (never `COPY`'d, and separately excluded by `api/.dockerignore`) for 10
  iterations before anyone ran `alembic upgrade head` inside the built image and noticed (found
  fixing T007, tracked as DB9). When touching `api/Dockerfile`, always verify with a real
  `alembic upgrade head` + `alembic current` inside the built image, not just a successful build.
- [M-010] To test `docker compose`/Alembic changes without touching the shared `decision-assistant`
  project's volumes/containers (which every worktree and the main tree share, since `compose.yaml`
  hardcodes `name: decision-assistant`), run with an isolated project name:
  `docker compose -p <throwaway-name> up -d db --wait`, then `docker run --rm --network
  <throwaway-name>_default -e DATABASE_URL=... <image> alembic ...`. Clean up the throwaway
  container/volume/network afterward. Never run bare `docker compose up`/`down` from inside a
  loop-iter-N worktree for testing purposes — it recreates the shared main-tree containers.
- [M-008] In Alpine images (musl libc), `localhost` in a healthcheck/wget/curl target can resolve
  to `::1` (IPv6) only, while a service bound with a plain `listen <port>;`/`0.0.0.0:<port>` is
  IPv4-only — the dial gets refused even though the service is up. Use `127.0.0.1` explicitly in
  Alpine-based healthchecks instead of `localhost`. (found iteration 8/9 via checker V7, DB3)
- [M-011] `compose.yaml` services with no `build.target` default to the Dockerfile's LAST stage,
  not the first/production one — `api/Dockerfile`'s last stage is `test` (adds pytest/dev extras),
  so every plain `docker compose build/run/up api` was shipping the dev-extras image as
  "production" for 12 iterations (found by checker V14, tracked DB10). Fixed by pinning
  `target: ${API_BUILD_TARGET:-base}` in compose.yaml and having `make test-api` set
  `API_BUILD_TARGET=test` to still get pytest. When adding a multi-stage Dockerfile to a compose
  service, always pin `build.target` explicitly — don't rely on stage order.
- [M-012] `api/Dockerfile`'s `test` stage never `COPY`'d `tests/` (and `.dockerignore` separately
  excluded it) — `docker compose run --rm api pytest` silently collected zero tests since T003
  removed the `.:/workspace` bind-mount (found fixing T009, DB11's sibling fix). Fixed by adding
  `COPY tests ./tests` to the `test` stage only. But the fix is incomplete: a real subset of tests
  still fails because they expect OTHER repo-root paths (`evaluation/`, `scripts/`, `sample_data/`,
  `.env.example`) at `/workspace/...`, outside `./api`'s build context entirely and not fixable with
  a `COPY` inside `api/Dockerfile` alone (tracked as DB11, open). When verifying any
  `api/Dockerfile`/`.dockerignore` change, always run the FULL test suite inside the built image,
  not just confirm pytest collects >0 tests — collection succeeding isn't the same as passing.
- [M-013] `Workspace`'s `WorkspaceDetail` response schema is built in `workspace/router.py` via
  `WorkspaceDetail(**_summary_fields(await _summarize(...)), embedding_profile=..., ...)` at 5
  separate call sites (create/get/rename/activate/archive) — no single factory function. Any new
  field added to `WorkspaceDetail` needs the same kwarg added at all 5 sites; grep for
  `WorkspaceDetail(` before adding a field to catch every site.
- [M-014] Splitting ORM classes out of `models.py` into a sibling domain module (e.g.
  `auth/models.py`) and then re-exporting them from `models.py`'s own tail (the pattern
  `evaluation/models.py` uses) only works if the target package's `__init__.py` is empty or at
  least doesn't import anything that needs `decision_assistant.models` back. Every package besides
  `evaluation` (`auth`, `workspace`, `ingestion`, `decisions`, `retrieval`) has an eager
  `__init__.py` that imports service/schema code needing the model classes — importing the
  submodule from inside `models.py`'s own tail triggers that `__init__.py` while `models.py` is
  still mid-initialization, causing a circular ImportError. Fix used in Iteration 18 (DB12): don't
  re-export from `models.py` at all; update every call site's import to the class's new home
  directly. Also remember to add the new model module to `api/alembic/env.py`'s explicit import
  list — `alembic check`/autogenerate won't see classes that aren't imported somewhere in the
  import graph `env.py` triggers, since `models.py` no longer defines them inline.
- [M-015] Use `make config` (not bare `docker compose config`) whenever inspecting rendered compose
  output in this repo — it pipes through `scripts/redact_config.awk` (sed originally, replaced
  Iteration 24) for SECRET/PASSWORD/API_KEY/TOKEN keys and embedded connection-string userinfo
  (added Iteration 22, DB5). The bare command still prints real secrets to stdout; `make config` is
  the safe default for tickets/logs/screen-shares.
- [M-016] `scripts/redact_config.awk`'s connection-string userinfo redaction is a plain greedy
  `sub(/:\/\/.*@/, "://REDACTED@", line)` — deliberately, not an oversight. `u:pa/ss@host` (password
  containing `/`) and `host/path@x` (path containing `@`, no userinfo) are textually indistinguishable,
  so no single-pass rule can separate them (checker V42, iteration 26 dead end). Iteration 26 tried an
  "authority-aware" version that bounded the match using the last `/` on the line before looking for
  `@`, which fixed the password-with-path case but still leaked a password-with-`/`-and-no-path case
  (`redis://:X+/Y@redis:6379`) — V42 confirmed no bounding heuristic closes both, and ruled that
  leak-safety must win: accept over-redacting the rare non-secret `http://host/path@x` shape (not
  present in `compose.yaml` today) rather than risk a real secret leak. Fixed in Iteration 27 back to
  the plain greedy form, now locked in by a checked-in fixture test (`make test-config-redaction`,
  `scripts/fixtures/redact_config/`) covering every case from V38/V40/V41/V42 — run it before editing
  this script, and do not reintroduce char-class or authority-bounding "precision" here without
  re-verifying it doesn't reopen the V41/V42 leak classes.
- [M-017] `alembic/env.py` calls `asyncio.run(run_async_migrations())` at module level in online
  mode. This means `alembic.command.upgrade()` (or any alembic command) can NEVER be called
  directly from code already running inside an asyncio event loop (e.g. FastAPI's `lifespan`) —
  `asyncio.run()` raises "cannot be called from a running event loop". Always dispatch alembic
  commands to a worker thread first (`asyncio.to_thread(...)`), as
  `api/src/decision_assistant/migrations.py:upgrade_to_head()` and its `lifespan` call site
  (`main.py`) now do (Iteration 28, T014). Also: `env.py` derives its DB URL from
  `config.get_settings()` itself, ignoring any `sqlalchemy.url` set programmatically on the passed
  `Config` object — don't bother trying to override it that way, it's silently overwritten.
- [M-018] `Settings`'s test-construction surface (`Settings(gemini_api_key=None)`-style calls, no
  `auth_jwt_secret`) is used across roughly 10 test files with no fake secret supplied. Any startup
  config validation added ahead of US5's secret-generation flow (T041) must NOT be a `Settings`
  model_validator/field_validator that fires unconditionally on every construction, or it breaks
  that whole surface. `validate_startup_config()` (`api/src/decision_assistant/config.py`,
  Iteration 28, T013) is deliberately a plain function, not wired into any automatic call path yet
  — T045 (Phase 7, US5) is the task tasks.md itself designates for wiring it into a real, blocking
  startup path, once first-run secret generation exists to supply real values by default. Do not
  "helpfully" tighten this into an automatic validator before then without first updating every
  affected test's `Settings()` call.
- [M-019] `logging.config.fileConfig()` defaults to `disable_existing_loggers=True`, which silently
  disables every logger NOT explicitly named in the ini's `[loggers]` section — including loggers
  configured before `fileConfig()` runs. `api/alembic/env.py` calls this (indirectly, via
  `alembic.command.upgrade` → `env.py`'s module-level `fileConfig(config.config_file_name)`), and
  since Iteration 28 (T014) this now runs inside the live uvicorn process at boot
  (`main.py`'s `lifespan` → `migrations.py:upgrade_to_head`). Always pass
  `disable_existing_loggers=False` when calling `fileConfig` from code that might run inside an
  already-initialized logging setup (checker V46; fixed Iteration 29). A silenced `uvicorn.error`
  logger is an easy miss in testing — the process looks healthy (health checks still pass), just
  produces zero startup/access/error log lines, so verify by actually reading boot logs for
  "Application startup complete."/"Uvicorn running on", not just process/health-check status.
- [M-020] Do not resolve any runtime path via `Path(__file__).resolve().parents[N]` traversal in
  `api/src/decision_assistant/` — `api/Dockerfile`'s production stage does a non-editable
  `pip install .`, which copies the package into site-packages, so a `__file__`-relative path
  computed there resolves somewhere under `/usr/local/lib/python3.12/...`, not the source tree
  layout the traversal assumes. This only surfaces under the actual production build, not under an
  editable/dev install, so it's easy to land and not notice until a checker (or user) builds the
  real image (checker V46; fixed Iteration 29, `api/src/decision_assistant/migrations.py`). Instead,
  use `Path.cwd()` for anything that needs an absolute path to a repo-tree file the process ships
  alongside code (e.g. `alembic.ini`) — both the Dockerfile (`WORKDIR /workspace/api`) and
  `compose.yaml` (`working_dir: /workspace/api`) pin the api service's cwd there.
- [M-021] **`compose.yaml:1` pins `name: decision-assistant`.** This overrides Compose's normal
  directory-based project naming — meaning ANY `docker compose` command run without an explicit
  `-p <name>` flag targets the user's real, shared default project (`decision-assistant-*`
  containers/volumes), REGARDLESS of which directory (main tree or any worktree) the command is
  run from. The usual mental model of "cd into an isolated worktree → compose commands are
  naturally scoped there" does NOT hold in this repo. Every `docker compose`/`make` invocation used
  for loop verification (build, run, up, test-api, test-web, etc.) MUST pass `-p <isolated-name>`
  explicitly (the `loop-iter-N-test`/`checker-iN` convention from M-010), with no exception — this
  bit the maker for real in Iteration 30 (a `docker compose run --rm web npm test` without `-p`
  started the user's actual stopped `db`/`api` containers). Contained with no lasting impact that
  time (images weren't rebuilt since they already existed; no migration ran since the real DB was
  already at head; the incident is fully described in iterations.md Iteration 30), but do not rely
  on being lucky twice — always double-check for `-p` before running a bare `docker compose`
  command against this repo, even a "just run the tests" one-liner that seems too simple to need it.
- [M-022] `compose.yaml`'s `web` service has no `target:` override (unlike `api`'s `target:
  ${API_BUILD_TARGET:-base}`, DB10's fix). `web/Dockerfile`'s last stage (`runtime`) is a bare
  `nginx:1.27-alpine` serving the built static files — no node, no npm. Compose always builds the
  last stage when `target:` is unset, so `docker compose run --rm web npm test` / `make test-web`
  cannot work as wired (`npm: not found`) — this is DB18, still open. To run web tests today, build
  `web/Dockerfile`'s `build` stage directly instead: `docker build --target build -t <tag> ./web`,
  then `docker run --rm <tag> npm test -- --run` — bypasses Compose's service definition entirely,
  so it needs no `-p` isolation (no shared project/containers involved).
- [M-023] M-022's DB18 workaround note is now stale — Iteration 32 (DB21) fixed both `test-api` and
  `test-web` Makefile targets to pass `-p decision-assistant-test` on every `docker compose`
  invocation, so the LITERAL `make test-api`/`make test-web` are now safe to run bare (no manual
  isolation needed) and no longer overwrite the real `decision-assistant-api:latest`/
  `decision-assistant-web:latest` image tags. `test-api` also tears its isolated project down after
  running (`down -v`); `test-web` currently does not (leaves the isolated `decision-assistant-test`
  volumes/network around for reuse — harmless, but don't assume they're gone). When adding a new
  Makefile test target that calls `docker compose` against this repo, always thread `-p
  decision-assistant-test` (or another name distinct from the pinned `name: decision-assistant`)
  through it from the start — don't rely on the caller remembering `-p` the way M-010/M-021 required.
- [M-024] `docker compose exec -T <svc> tar -cf <host-path> ...` does NOT work — the `tar` process
  runs INSIDE the container, so a host filesystem path passed as its output file doesn't exist
  there and it fails with `Cannot open: No such file or directory`. To pull a directory out of a
  running container/volume via `exec`, always stream through stdout and redirect on the host side:
  `docker compose exec -T <svc> tar -cf - -C <container-dir> . > <host-path>` (found while writing
  `scripts/backup.sh`, T035, Iteration 34).
- [M-025] `scripts/restore.sh` (T036) does NOT produce a clean-slate restore: `pg_dump --clean
  --if-exists` and `tar -x` both only drop/overwrite objects that are present in the archive —
  neither deletes an extraneous DB table or upload file added after the backup was taken. Verified
  live (Iteration 35): a table and a file created post-backup both survived a full restore intact.
  This matches quickstart.md Section 5's actual flow (delete the data volumes, THEN restore into an
  empty target), so it is correct for the documented use case, not a bug — but do not assume
  `scripts/restore.sh` is safe to run against a live, already-populated stack expecting it to purge
  drift; it won't.
- [M-026] `scripts/backup.sh`/`scripts/restore.sh` cannot be invoked from INSIDE the `api`
  container (e.g. from `main.py`'s `lifespan`, or any in-process Python code) — they shell out to
  `docker compose exec db pg_dump`/`docker compose exec api tar`, which need the HOST's `docker`
  CLI and a running Compose context. `api/Dockerfile`'s image (`python:3.12-slim` base) has
  neither a `docker` CLI nor a `pg_dump` client binary, and `compose.yaml` mounts no docker
  socket into `api`. This blocks T037's literal "single implementation, two call sites" framing
  for T014's startup auto-backup — see debt DB22 (Iteration 36) for the three real options (new
  apt dependency, docker-socket mount, or a separate DB-native routine), each of which needs a
  human decision per AGENTS.md's escalation rule, not a maker default.
- [M-027] Never install a generic, unversioned `postgresql-client` apt package to talk to a
  version-pinned Postgres server. Debian's own repo only ever offers the CURRENT default major
  version for that release (v17 on trixie, v15 on bookworm at time of writing) — neither matches
  `compose.yaml`'s pinned `pgvector/pgvector:pg16`. Confirmed live (Iteration 37): a v17 `pg_dump`
  emits syntax a v16 `psql` rejects on restore (`SET transaction_timeout = 0;` — a v17-only GUC),
  failing with `unrecognized configuration parameter`. Get an exact-matching client via the
  official PGDG apt repo (`apt.postgresql.org`, package `postgresql-client-<major>`) instead —
  see `api/Dockerfile`'s two-stage apt install (curl+gnupg to fetch the PGDG key, then the pinned
  package, then purge curl+gnupg). Don't try to shortcut this by copying the `pg_dump` binary out
  of the `pgvector/pgvector:pg16` image directly either — it dynamically links ~25 shared
  libraries (GSSAPI/Kerberos/LDAP/GnuTLS chain), and that image is Debian bookworm (12) vs. the
  api image's trixie (13), a cross-release glibc/ABI risk not worth taking.
- [M-028] `api/tests/unit/test_app.py::test_lifespan_closes_provider_factory_when_application_errors`
  is the ONLY test in the suite that enters `app.router.lifespan_context(app)` directly (grepped:
  no other file uses `lifespan_context` or `with TestClient(`) — every other test's plain
  `TestClient(app).get(...)` does NOT trigger FastAPI's lifespan. That one test therefore runs
  every `lifespan` startup step for real up to its `yield`, including `upgrade_to_head()` (already
  true before Iteration 37) and now `create_pre_migration_backup()` — a real `pg_dump` subprocess
  and a real write into the host-bind-mounted `./backups` directory. Iteration 37 added a
  `monkeypatch.setattr("decision_assistant.main.create_pre_migration_backup", ...)` no-op stub to
  that one test to stop it polluting the host filesystem on every `make test-api` run. Any FUTURE
  lifespan step added before this test's `yield` needs the same treatment, or it'll silently
  become a real, undesirable side effect of running the test suite.
- [M-029] The pre-migration backup (`create_pre_migration_backup`) must be gated on
  `migrations.is_upgrade_pending(settings)`, not run unconditionally on every boot. Checker V63
  (iteration 37) found that at low retention, no-op-restart backups rotate away the only real
  pre-migration archive before a genuine migration ever needs it. `is_upgrade_pending` compares
  the DB's current Alembic revision (`MigrationContext.get_current_revision()`) against the
  script directory's head (`ScriptDirectory.get_current_head()`); a fresh/empty DB (`None`
  current revision) counts as pending. See `api/src/decision_assistant/migrations.py:39-78` and
  `main.py`'s `lifespan` (iteration 38).
- [M-030] **DB24 (open, needs human/checker decision):** the DB18/DB21 Makefile fixes that D3's
  `checker-pass` (V54-V57) is based on were never merged into `improvement` — they exist only on
  an unmerged `loop-iter-31` branch/worktree (`3a5c6af`, `7eb13f6`), confirmed via
  `git log --oneline --all` and `git worktree list` (worktree still present at
  `/Users/saurav/projects/loop-iter-31`). The current `improvement` branch's `Makefile`/
  `compose.yaml` still have the ORIGINAL bug: bare `make test-web` builds the wrong (npm-less
  nginx) stage, and neither `test-api` nor `test-web` is scoped to an isolated Compose project —
  both can still overwrite the real `decision-assistant-{api,web}:latest` image tags if run
  literally on this branch. Do NOT run bare `make test-api`/`make test-web` on `improvement`
  as-is; use an explicit `-p`/`COMPOSE_PROJECT_NAME` override (see M-010/M-021) until DB24 is
  resolved (either fast-forward-merging `loop-iter-31`, or re-doing the fix directly on
  `improvement`).
- [M-031] When starting any isolated verification stack, use an explicit `-p`/
  `COMPOSE_PROJECT_NAME` on EVERY command including the very first one. A bare
  `docker compose run --rm api ...` (no `-p`) resolves to the real pinned project name
  (`compose.yaml`'s `name: decision-assistant`) and will start real service containers (e.g.
  `decision-assistant-db-1`) even if the command then fails for an unrelated reason (iteration 38:
  a missing test file). Low-risk if caught immediately (`docker compose stop <service>` restores
  the prior `Exited` state, no data loss), but avoidable by never typing the bare form first.
- [M-032] DB24's fix (iteration 39) was hand-ported, not git-merged: `loop-iter-31`'s two
  commits (`3a5c6af` DB18, `7eb13f6` DB21) sit on top of `3e2f32f`, but `improvement`'s working
  tree carries iterations 33-38's own uncommitted changes to the same files
  (`Makefile`/`compose.yaml`), so a real `git merge` would have required committing those first
  — out of scope for a single coherent increment. The diffs were re-applied by hand instead:
  `compose.yaml`'s `web` build block gained `target: ${WEB_BUILD_TARGET:-runtime}`; `Makefile`
  gained `TEST_PROJECT := decision-assistant-test` and both `test-api`/`test-web` now pass
  `-p $(TEST_PROJECT)` on every `docker compose` call. The `loop-iter-31` worktree/branch
  (`/Users/saurav/projects/loop-iter-31`) is now fully superseded and safe to remove, but
  deleting a worktree/branch is a destructive git op the maker doesn't take unilaterally — left
  for a human. Do not merge it later; its content is already in `improvement`'s working tree
  and a merge at this point would conflict or duplicate.
- [M-033] `main.py`'s `lifespan` gate (`if is_upgrade_pending(...): create_pre_migration_backup(...)`)
  needs its own test distinct from testing `is_upgrade_pending`/`create_pre_migration_backup`
  individually — checker V68 found that stubbing both functions out (as the pre-existing
  lifespan test does, see M-028) proves neither function's internals, but proves nothing about
  whether the `if` gate itself, or the call order relative to `upgrade_to_head()`, is correct.
  Deleting the gate or reordering the calls left all prior tests green. Fixed in
  `test_app.py` (iteration 40) with 2 tests that spy on `upgrade_to_head`/
  `create_pre_migration_backup` call counts across the real `lifespan_context`, not just mock
  them away.
- [M-034] Every isolated checker/loop-iter project (`checker-iN`, `loop-iter-N-test`, etc.,
  see M-010) builds and leaves behind its own ~2.6GB `<project>-api` image unless someone
  explicitly `docker rmi`s it — `down -v` (or `make test-api`'s own teardown) removes
  containers/volumes/networks but never images. By iteration 41 this had accumulated to 57
  images / 47.86GB and filled the Docker Desktop VM's virtual disk (distinct from host disk
  space — `df -h /` on the host showed plenty free while every DB-touching test failed with
  `asyncpg.exceptions.DiskFullError`), the same failure class as the earlier V34 blocker.
  Fixed by `docker rmi` on every image matching `checker*`/`loop-iter-*-test-*`/
  `decision-assistant-test-<N>-*`/`da-iter*` (confirmed by exact name first — never delete
  anything matching bare `decision-assistant-{api,web}` or the current
  `decision-assistant-test-{api,web}` with no trailing iteration number), then
  `docker image prune -f` and `docker builder prune -f` for the dangling-layer/build-cache
  remainder; freed ~37GB total. If a `make test-api`/live-DB test run fails with a disk-full
  error and the host itself has free space, check `docker system df` and `docker run --rm
  alpine df -h /` (VM-internal view) before assuming a code regression — and get human
  approval before pruning, per Iteration 41/42's precedent, since it deletes images (even
  though only throwaway ones untouched by any script).
- [M-035] `psql -v name=value -c "... :'name' ..."` variable interpolation did NOT
  substitute when run via `docker compose exec -T db psql -U ... -d ... -v pw="$X" -c "..."`
  in this repo's Postgres image (`pgvector/pgvector:pg16`) — every attempt raised `ERROR:
  syntax error at or near ":"`, both for a real value and a diagnostic literal, ruling out a
  quoting mistake specific to the real attempt. Root cause not pinned down (dead end, do not
  re-attempt this exact form expecting a different result). Reliable alternative used
  instead (Iteration 43, rotating the real DB role password without ever putting the
  password in a shell argument, command string, or printed output): generate the value in
  Python, build the full SQL statement as a Python string (SQL-escaping any embedded `'` by
  doubling it), and pipe it to `psql` over stdin via `subprocess.run([...], input=sql.encode())`
  — no `-c`, no `-v`. Works reliably and keeps the secret out of `ps`/shell history/this
  session's own transcript.
- [M-036] `main.py`'s `lifespan` now runs a T021 startup recovery sweep for `IngestionJob`
  rows stuck `running` after a crash/restart, reusing `LocalIngestionDispatcher` (imported
  from `documents/router.py`) fired via `asyncio.create_task`, not `background_tasks.add_task`
  (there's no request in scope at startup). `EvaluationRun` rows are NOT yet covered by this
  sweep — that's T023, a separate increment, not a gap in T021.
- [M-037] Fixed DB27 (iteration 46): `recover_and_requeue` (`jobs/recovery.py`) gained a
  `statuses: Sequence[str] = ("running",)` parameter (default preserved for `test_jobs_recovery.py`'s
  existing "pending/completed untouched" assertion). `main.py`'s IngestionJob sweep now
  passes `statuses=("running", "pending")` — a job whose fire-and-forget dispatch crashed
  before ever reaching `running` was previously invisible to the sweep forever. Also fixed
  DB27's GC finding: `asyncio.create_task` results are now held in
  `application.state.startup_redispatch_tasks` (a set, pruned via `add_done_callback`) so the
  event loop isn't the only reference holder.
- [M-038] Rewrote T020's integration test (`test_ingestion_restart_recovery.py`) to run the
  *real* redispatch path end-to-end (real `LocalIngestionDispatcher`/`IngestionService`, fake
  providers) instead of asserting on a stub call + `pending` status — checker V85 correctly
  flagged the old version as proving nothing about terminal state. Two things had to be
  worked around, both worth remembering for any future test that exercises this path:
  (1) `decision_assistant.documents.router`'s module-level `session_factory` (from
  `decision_assistant.db`) is a process-wide singleton bound to whichever event loop opens
  its first connection; a second `pytest.mark.asyncio` test (fresh loop per test by default)
  reusing it fails with "Future ... attached to a different loop" — monkeypatch
  `router_module.session_factory` to a fresh `create_async_engine` scoped to the test's own
  loop instead, and dispose it after. (2) `EmbeddingCache` dedup is workspace-scoped, not
  global (`_resolve_embedding_cache` filters by `workspace_id`) — `conftest.py` truncates the
  test DB only once per pytest session, so any real ingestion here is *visible to every other
  test in the same run*, and `test_ingestion_service.py::test_identical_chunks_share_one_embedding_cache_entry`
  asserts an unscoped global `count(embedding_cache) == count(distinct passage.content_hash)`.
  Any test elsewhere that ingests real content leaves rows that can break that assertion.
  Fixed by deleting the test's own `Workspace` row in a `finally` block after each test
  (`workspaces.id` cascades `ON DELETE CASCADE` through documents/versions/jobs/passages/cache) —
  general lesson: a real-DB integration test that shares a session-scoped, not per-test,
  database must clean up after itself rather than relying on an assumed-clean slate.
- [M-039] T023 (evaluation-run recovery, same pattern as T021/T011) cannot reuse
  `recover_and_requeue` as-is: it requires the model to have `attempt_count` (int) and a
  settable `error` attribute. `EvaluationRun` (`evaluation/models.py:58`) has neither —
  no `attempt_count` column, and its failure field is named `failure` (JSONB), not `error`.
  Setting `row.error = {...}` on it would silently create an unmapped, unpersisted Python
  attribute rather than raise — a real footgun if someone just wires it up without checking.
  This needs a schema migration (new Alembic revision) plus a decision on the `failure`/`error`
  naming mismatch (rename, or make `recover_and_requeue`'s error-field name configurable) —
  escalated to the human per AGENTS.md's ask-before-schema-changes rule (iteration 47), not
  attempted.
- [M-040] T023 implemented (iteration 48) per human decision ("add a new migration"):
  Alembic revision `0013_eval_run_attempt_count` adds `evaluation_runs.attempt_count`. Kept
  `failure` as the column name (no rename — avoids touching `evaluation/service.py`'s existing
  `run.failure` usages and the web `EvaluationResults.tsx` component that reads it) and instead
  made `recover_and_requeue` accept `error_field: str = "error"` (default preserves
  `IngestionJob` callers unchanged); `main.py` passes `error_field="failure"` for the
  `EvaluationRun` sweep. Also applied DB27's `statuses=("running", "pending")` fix to
  `EvaluationRun` from the start, not just `("running",)` as T023's original text said —
  `evaluation/router.py`'s `start_run` has the exact same fire-and-forget-before-`running`
  crash window as ingestion's upload path, so leaving it `running`-only would have
  reintroduced a bug class already fixed once. Revision-id note: alembic_version.version_num
  is `varchar(32)` — `0013_evaluation_run_attempt_count` (33 chars) failed
  `StringDataRightTruncationError` on `alembic upgrade head`; renamed to
  `0013_eval_run_attempt_count` (27 chars). Watch this limit on future revision names.
  `EvaluationBackgroundRunner`'s `session_maker` default (like `documents/router.py`'s
  dispatch path, M-038) is a class-definition-time binding to the process-wide
  `decision_assistant.db.session_factory` singleton — monkeypatching the module attribute
  after the fact does nothing; a test needing a loop-local engine must wrap the class itself
  (see `test_evaluation_restart_recovery.py`'s `_loop_local_evaluation_runner`).
- [M-041] Fixed DB28 (iteration 49): `recover_and_requeue`'s terminal-`failed` path never
  stamped a terminal timestamp — a pre-existing gap in BOTH `IngestionJob` (`finished_at`) and
  `EvaluationRun` (`completed_at`), not just the one the checker happened to flag. Added
  `finished_at_field: str | None = None` (default preserves old behavior for any caller that
  doesn't pass it), same configurable-field-name pattern as `error_field` (M-039/M-040) since
  the two models name their timestamp column differently too. Made the maker-level call to fix
  both call sites for consistency, and to apply DB28's fix symmetrically rather than leaving
  ingestion with the identical, now-known gap — not a schema change, no ask-first needed
  (existing nullable columns, just previously never written by this code path).
- [M-042] T024/T025 (iteration 50): T025's list-view half (`DocumentTable.tsx`'s failed/retry
  state) already existed from an earlier iteration, never marked `[X]` — only the detail view
  (`SourceViewer.tsx`) was missing it, and `DocumentDetail` had no `status`/`stage`/`progress`/
  `error` fields to render it from (T024's actual gap). Extracted the list view's local
  `canRetry`/`retryableErrorCodes` into `IngestionStatus.tsx`'s exported `canRetryDocument` so
  list and detail share one definition of "is this failure retryable" (AGENTS.md: React must
  not become a second source of domain truth — a single client function is the least-bad
  compromise, since the actual retryable/not-retryable judgment is still server-supplied via
  `error.retryable`/`error.code`, the function just centralizes reading it).
- [M-043] Fixed DB29/DB30 (iteration 51, checker V94/V95 against iteration 50's T024/T025).
  DB29's backend half: `DocumentService.retry()`'s original query only checked "is there A
  failed job", not "is the LATEST job failed" — a job left `pending` by an in-flight retry was
  invisible to that check, so a second retry sailed through and dispatched a second concurrent
  ingestion against the same `DocumentVersion`. Same class of bug as the DB27
  latest-vs-any-matching-row lesson, different code path. DB29's frontend half needed
  `Workspace.tsx`'s `handleRetry` to re-fetch the open `sourceDocument` after a successful
  retry — without it the modal never learns the retry happened and the (still-enabled) button
  invites exactly the backend race the fix above closes.
  DB30: `api/tests/support/document_fixtures.py` is the new location for
  `RecordingDispatcher`/`WORKSPACE_ID`/`documents_api`/`_workspace_id`, shared by
  `test_documents_upload.py` and `test_documents_detail.py` (split from the single
  `test_documents_api.py` that grew past 500 lines). A gotcha hit while writing DB29's
  regression tests: `documents_api`'s fixture binds every HTTP call in a test to the SAME
  `db_session`/transaction (bypassing `Depends(get_session)`'s real per-request session), so
  `created_at`'s `server_default=func.now()` (Postgres transaction-start time, not
  statement time) ties between two jobs created by "different requests" in the same test —
  breaking any assertion that depends on `ORDER BY created_at DESC` picking the right row.
  Calling `db_session.commit()` mid-test "fixes" the tie but makes that test's fixture data
  (e.g. the fixed `WORKSPACE_ID` workspace row) permanently committed, breaking every later
  test in the same file that reuses that same fixed ID (DB truncates once per pytest session,
  not per test) with a `UniqueViolationError`. The actual fix: directly bump the newer job's
  `created_at` forward by hand (`session.flush()`, no commit) to simulate what a real request
  boundary's fresh `now()` would produce, keeping the row uncommitted/rollback-able.
- [M-044] Fixed V97 (iteration 52). `Workspace.tsx`'s `handleRetry` guarded its post-retry
  refresh with `sourceDocument?.id === documentId` — a closure read of the state value from
  the render that created the handler, so the guard stayed true after the user closed the
  dialog (reopening it) or opened another document (overwriting it). Note where the guard
  sits: it runs *after* `await retryDocument`, so it already sees post-close reality if it
  reads a ref — the closure was the whole bug. Fixed with `openDocumentIdRef`, kept in sync by
  a single `openSourceDocument(detail)` helper that every `setSourceDocument` call site goes
  through (state and ref must move together; a bare `setSourceDocument` anywhere would
  silently desync them). A second check after `await getDocument` covers the fetch-in-flight
  window, where the ref can still change mid-await.
  Test lesson, worth reusing: the first version of these tests passed even with the bug
  reintroduced. `await act(async () => { resolve(); await Promise.resolve(); })` is **not**
  enough to drive an `await A -> await B -> setState` chain to completion — one microtask tick
  lands before the second await resolves. Awaiting a real macrotask inside `act` (the
  `finishRetry` helper) makes the failure surface. Any test that resolves a held promise and
  then asserts on a multi-await continuation needs that, and a mutation check is the only way
  to notice the difference. Mutants confirmed: restore the stale read → all 3 tests fail;
  drop the post-fetch re-check → only the fetch-in-flight test fails.
- [M-045] `web/src/test/documentFixtures.ts` is the shared home for `completedDocument`,
  `failedListItem`, and `detailFixture`. Test files were splitting and duplicating document
  shapes to dodge the 500-line cap; put new shapes here instead.
- [M-046] Fixed DB31 (iteration 53): `DocumentService.retry` now takes a row lock —
  `select(Document).where(Document.id == document_id).with_for_update()` before reading the
  latest `IngestionJob`. Rationale: DB31 offered "row lock" or "partial unique index on
  in-flight jobs"; the lock avoids a schema migration, so no human approval gate. `get_session`
  commits at request end, so the lock spans the whole retry transaction and the loser re-reads
  the winner's committed `pending` job → 409.
  Test lesson: a concurrency test cannot use the shared `db_session` fixture — one session makes
  the row lock re-entrant and the race disappears. Open two real sessions from a fresh engine
  (copy the `test_documents_retry_concurrency.py` shape) and delete your own rows in a `finally`.
  Deterministic discriminator without timing flake: hold the winner's transaction open past its
  `retry()` call, start the loser, `assert not task.done()` after a short sleep, then commit and
  assert the loser's 409. The `assert not task.done()` line is what kills the no-lock mutant.
- [M-047] Seeding several tables in one `session.add()` + single `commit()` fails here:
  SQLAlchemy inserted `documents` before `workspaces` and hit `documents_workspace_id_fkey`
  (adding the missing `users` table to the metadata did not change the order). Flush one level
  at a time — add parent, `await session.flush()`, then child. The rest of this suite already
  seeds that way; follow it instead of relying on flush ordering.
- [M-048] `api/Dockerfile` copies source before `pip install .`, so any source edit invalidates
  the dependency layer: every `docker compose build api` re-downloads the full dependency set and
  Docling artifacts (~5-15 min per iteration; iteration 53 spent ~1h across four build cycles).
  When an iteration needs repeated in-container mutation checks, budget for that, or raise the
  Dockerfile ordering as its own task (reorder `COPY` so deps cache) before running a phase that
  needs many small edits. Also, in this session `run_in_terminal` in sync mode returned no
  output; async mode worked, and `docker compose build ... > /dev/null` keeps running (orphaned)
  after the wrapping tool call gives up, which makes the shell look free while a build still runs.- [M-049] D6 executed live (iteration 54). The stack is runnable for a live check without touching
  the real project: `docker compose -p decision-assistant-d6 up -d db api --wait` with
  `API_PORT=18000` **exported** and `BACKUP_DIR` pointing outside the repo. Signup is open
  (`POST /api/v1/auth/signup`), workspaces are under `/api/v1/workspaces`, documents under
  `/api/v1/workspaces/{id}/documents`, evaluations under `/api/v1/workspaces/{id}/evaluations`.
  To interrupt honestly use `docker compose kill api` (SIGKILL), not `restart` (graceful SIGTERM
  can let the job finish). Result: the sweep requeues the job and it completes; job count stays 1
  with `attempt_count 1`.
  Two shell gotchas cost most of this iteration's wall clock: (1) any env var that changes a
  published port must be **exported**, because each `docker compose` invocation re-evaluates
  `${API_PORT:-8000}` — the post-kill `up` otherwise recreates the container on the default port
  and the host curls a dead socket; (2) non-interactive compose calls here (`make test-api`,
  `docker compose exec -T`) hang or suspend unless stdin is closed — always add `< /dev/null`,
  and never share one log file between two concurrent runs of the same script (the `>` truncation
  leaves a sparse hole; `cat` then shows only the header while `tail` shows the real output).
- [M-050] The app configures no logging at all (`getLogger`/`basicConfig`/`dictConfig` absent from
  `api/src`). quickstart.md Section 3 nonetheless tells the operator to verify recovery with
  `docker compose logs api | grep -i "recover\|requeue"`. Until US7 (T056) adds real logging
  configuration, emit operational messages through `logging.getLogger("uvicorn.error")` — that
  logger has handlers configured by uvicorn, so the line actually reaches the container log.
- [M-051] Production packaging gap (DB32): `evaluation_dataset_path` defaults to
  `/workspace/evaluation/questions.json`, which is outside the `api` build context, so no
  evaluation run can start in a production image. The test suite hides this because
  `compose.test.yml` bind-mounts the repo root read-only. Any "run it against a production stack"
  check for evaluation endpoints will fail until a human picks a packaging fix.
- [M-052] DB32 resolved by human decision (iteration 55): evaluation is **development only**. The
  benchmark stays in the repo and out of the image; docs say so (`quickstart.md` §3, `README.md`,
  `docs/install.md`, `AGENTS.md` gotchas), and `_load_dataset` raises `evaluation_unavailable` (503)
  when the file is absent, keeping `dataset_invalid` for a corrupt one — so an operator is not told
  to repair a file that was never shipped. Do not "fix" this by bind-mounting `evaluation/` into
  the api service: that breaks the no-source-bind-mount rule the whole packaging story rests on.
- [M-053] D7/US3 is blocked on the schema, not on missing code (DB34, iteration 56).
  `decisions.document_version_id` and `decision_evidence.passage_id` are NOT NULL with
  `ondelete="CASCADE"`, so the "truncate the corpus-derived tables, leave decisions alone" design in
  `data-model.md`/T028 cannot work: the FK cascade takes the decisions with it. Lesson for future
  scoping: for any "delete derived data but keep the domain rows" task, read the **ondelete** clauses
  of the references pointing at the derived tables before writing the delete — a test that asserts
  the SQL scope will pass while rows vanish. Prefer an integration assertion that reads the
  supposedly-surviving rows back.
- [M-054] Iteration 57: the DB35 Dockerfile refactor was **authored and committed by the human**
  (`281a525`). When someone else's change lands on the branch, the maker's job is to verify it
  against the recorded plan and externalize the evidence — not to re-implement or bless it. Measured
  result of the refactor: a source-only edit now rebuilds the api image in ~6 s (base) / ~7 s (test)
  with the dependency+model layer `CACHED`, against 5–15 minutes before. Watch for this class of
  finding when verifying a dependency-layer change: compare `pip freeze` between the old and new
  images and expect exact parity — any difference is a **floating transitive dependency**, not a
  layering bug (here `docling-core` 2.98.1 → 2.99.0, DB36).- [M-055] Fixed DB34's schema blocker (iteration 58): revision `0014_decision_setnull_fk` makes
  `decisions.document_version_id`/`decision_evidence.passage_id` nullable and switches their FKs
  from `ON DELETE CASCADE` to `ON DELETE SET NULL`, matched in `decisions/models.py`. Constraint
  names for unnamed FKs created inline in `0001_initial.py` follow Postgres's default
  `<table>_<column>_fkey` convention (`decisions_document_version_id_fkey`,
  `decision_evidence_passage_id_fkey`) — confirmed via `\d <table>` on a fresh DB before writing
  the migration, don't guess. Second hit of M-040's `alembic_version.version_num varchar(32)`
  limit: `0014_decisions_nullable_derived_refs` (36 chars) failed
  `StringDataRightTruncationError`; renamed to `0014_decision_setnull_fk` (24 chars). Always count
  a new revision id's length before writing the file, not after the upgrade fails. This iteration
  did NOT touch `decisions/schemas.py`, `decisions/service.py`, or `decisions/extractor.py` for an
  implicit non-null assumption on either column — nothing writes `NULL` into them yet (T028 will),
  so no live break exists today, but check those three files when implementing T026-T031.
- [M-056] `embedding_cache.embedding` and `passages.embedding` (`pgvector`, `Vector(768)`) are
  NOT NULL despite each having a nearby code comment calling it a "deprecated duplicate" — that
  comment describes retrieval's read path (semantic search reads `EmbeddingCache.embedding`, not
  `Passage.embedding`), not the column's nullability. Any test/seed inserting a `Passage` or
  `EmbeddingCache` row must supply a real 768-float vector (e.g. `[0.0] * 768`), not `None` or a
  short placeholder list — Postgres rejects both a NULL and a wrong-dimension vector. (found
  iteration 59, `test_corpus_rebuild.py`)
- [M-057] Fixed DB37/DB38 (iteration 60), both per explicit human decision (schema change +
  scope change, ask-first per AGENTS.md):
  - DB37: `retrieval_traces` has no FK to `passages`/`document_versions` (`selected_passage_ids`
    is plain JSONB, not a foreign key), so it does not need to be part of a corpus rebuild's
    delete scope at all — the human chose to just stop deleting it, rather than adding a schema
    change to `conversation_messages.trace_id`/`question_answers.trace_id`. Zero migration.
  - DB38: `decisions.workspace_id` (revision `0015_decisions_workspace_id`) is the only way
    workspace membership survives a rebuild, since the corpus-derived chain
    (`document_version_id` -> `documents` -> `workspace_id`) is exactly what a rebuild severs.
    Backfilled from that same chain before `NOT NULL`, so no data loss on existing rows.
  Together these are the second and third schema/scope decisions in the DB34 lineage — the
  pattern going forward for "must survive a rebuild" data is: does it have its own workspace_id
  or an independent (non-corpus) path to one? If not, that's the actual blocker, not the
  CASCADE/TRUNCATE mechanics that surface first.
- [M-058] `decisions/service.py`'s `get_decision` evidence query and `list_decisions`/
  `_require_decision` no longer join through `DocumentVersion`/`Document` at all — scoping now
  reads `Decision.workspace_id` directly, and the evidence-to-`Passage` join is `outerjoin`, not
  `join`. Any FUTURE code touching decision retrieval should keep using `Decision.workspace_id`
  for scoping, not resurrect the document-version join — it's both simpler and correct when
  `document_version_id` is `NULL` post-rebuild, whereas the join silently returns nothing.
- [M-059] Iteration 61's `CorpusRebuildCoordinator` (`workspace/rebuild/coordinator.py`) design,
  three points future work must not accidentally violate:
  - A rebuild recreates each document under its **same** `id` on purpose — that is the only thing
    that makes `decisions.document_version_id` re-linkable afterward (document identity is the
    join key; the old `document_version_id`/`passage_id` are gone forever the moment the FK's
    `ON DELETE SET NULL` fires). Never generate a fresh `document_id` for a rebuild's recreated
    document.
  - `IngestionService.ingest()` now takes `extract_decisions: bool = True`. A rebuild always
    passes `False` — decisions are never re-extracted from a rebuilt document; the preserved,
    re-linked decision is the sole record (D7's "unchanged"). If a future caller of `ingest()`
    needs decisions skipped for a different reason, reuse this flag rather than adding another
    ad hoc parameter.
  - Passage re-linking is intentionally conservative: exact `content_hash` match or nothing
    (`citation_stale=true`). Do not "improve" this with fuzzy/similarity matching — a wrong guess
    would misattribute evidence to different text, which is worse than a flagged-stale citation.
  - Two coordinator entry points exist for a reason: `dispatch_corpus_rebuild` creates its own
    `CorpusRebuild` row (lifespan/T029's per-workspace scan), `dispatch_pending_rebuild` continues
    an already-committed one (T030's retry, which must create the `pending` row synchronously in
    the request so `GET .../corpus-rebuild` reflects it immediately, and only backgrounds the
    long part — creating a second row in the background would race the single-active-rebuild
    unique index against the one the request already committed).
  - DB40 residual gap (see debt.md): `timelines/service.py`, `retrieval/repository.py`, and
    `answering/service.py` still inner-join on `Passage`/`passage_id`, so a decision whose *every*
    evidence row fails to re-link (reshaped chunking) still drops from those reader paths even
    though `GET /decisions` keeps showing it (DB38's outerjoin). **Resolved in iteration 62 by
    re-linking, not by outer-joining (see M-060)**: the readers need a real `passage_id` to return
    a passage at all, so tolerating `NULL` was never an option for retrieval/answering.
- [M-060] Iteration 62 closed the three D7 rebuild gaps the checker found (DB40 residual, DB41,
  DB42). Three durable rules:
  - **Quote is stored, not derived.** `decision_evidence.quote` (revision `0016_evidence_quote`)
    is the evidence row's stable identity across a rebuild. Readers (`decisions/service.py`'s
    `_evidence_quote`, `timelines/service.py`'s `_evidence_response`) serve the stored quote and
    only fall back to slicing the passage for rows written before 0016. Never reintroduce a
    passage slice as the primary source: after a rebuild the passage is a different chunk than
    the one the quote was extracted from.
  - **Re-link order is hash, then quote text, then stale.** `_match_evidence` tries an identical
    `content_hash` (passage content byte-identical, original offsets still valid), then locates
    the stored quote inside the new passages (offsets and `content_hash` are updated to the
    passage it actually landed in, keeping the row coherent for the correction API's hash check),
    then leaves `passage_id` NULL + `citation_stale = true`. No fuzzy matching — misattributing
    evidence to different text is worse than a flagged-stale citation.
  - **The rebuild's row must not live in the rebuild's transaction (DB41).** The corpus swap is one
    transaction that commits at the end (V108: readers keep seeing the old corpus), so the
    `CorpusRebuild` row is committed BEFORE the work starts and every progress change is committed
    in its own short session (`workspace/rebuild/dispatch.py`'s `_progress_hook`). The long
    transaction must never touch `corpus_rebuilds`, or the two writers block each other on the row
    lock. Same change made `mark_interrupted_rebuilds` mandatory: a committed-before-work row
    survives a crash, and the single-active partial unique index then blocks every later rebuild
    for that workspace. The lifespan sweeps those to `failed` before dispatching new ones.
  - Two constants to remember: a document with **no active version** is preserved by the truncate
    (DB42 — its stored file and retry path are the only record of it), so `_snapshot_workspace`
    returns `preserved_document_ids` and the truncate takes it as a `notin_` filter; and the
    rebuild's dispatch half now lives in `workspace/rebuild/dispatch.py`, not `coordinator.py`,
    to keep both files under the 500-line cap.
- [M-061] Iteration 63 fixed DB43 (checker V118) with the human's **option A**: a rebuild that
  fails on any document rolls back whole.
  - **A failed rebuild commits nothing.** `execute_rebuild` raises `RebuildAborted(error)` on the
    first document re-ingestion failure, while the corpus transaction is still open;
    `dispatch._run` catches it, rolls that transaction back, and only then records `failed` +
    the offending document's error code on the `CorpusRebuild` row (its own session, DB41). The
    workspace keeps the corpus it had before the attempt — documents with their active versions,
    passages, and every decision/evidence link — so a retry re-runs against real data instead of
    finishing `completed 0/0` over the DB42-preserved leftovers (V118's second symptom).
  - Corollary worth keeping: after an aborted rebuild the workspace still reports
    `corpus_reset_required`, so `/ready` stays not-ready and the next startup re-dispatches it.
    That is the correct state, not a stuck one. Pre-DB43 the emptied corpus made the reset check
    find nothing to compare, which is why V118 saw `/ready` return 200 over no data.
  - **Layout rule:** `coordinator.py` is orchestration + truncate scope; the snapshot/re-link
    half now lives in `workspace/rebuild/relink.py` (`snapshot_workspace`, `relink_document`).
    DB43's exception class plus its docstring pushed `coordinator.py` from 485 to 515 lines, over
    AGENTS.md's cap; a pure move brought it back under. Any further growth there gets a split,
    not a longer file.
  - Residual, corrected by checker V119 (2026-09-26): a single-document retry
    (`POST /documents/{id}/retry`) after an aborted rebuild returns **409**, because DB29's rule
    requires the document's latest `IngestionJob` to be `failed` and this iteration's fix runs
    from the rebuild retry instead. The duplicate-decision path this note originally worried about
    is therefore not reachable through the API. The rebuild retry stays the documented recovery
    path.
- [M-062] Iterations 64-66 closed D7's test/doc half (T027, T033) and D8's automated half (T034).
  - **An HTTP test of the rebuild must poll through a 404 window.** `GET .../corpus-rebuild`
    answers 404 `corpus_rebuild_not_found` until the background dispatch commits its first row —
    poll it rather than skipping it, so "no rebuild has run yet" stays distinguishable from a real
    failure. And because a fake-provider rebuild finishes inside one poll interval, `running` is
    unobservable unless the rebuild is gated at its first embedding call and released only after
    `running` has been polled *and* that poll's reads verified stable.
  - **When asserting "reads unchanged" across a rebuild, normalize exactly three things:**
    `passage_id`, `document_version_id`, and `stale`. A completed rebuild legitimately rewrites the
    first two (DB40's re-link) and the workspace-revision bump flips the third; every other field
    (statements, statuses, quotes, titles, turn numbers, questions, answers, timestamps) must match
    byte for byte.
  - Business routes are owner-scoped: a directly seeded workspace needs `owner_user_id`, or every
    owner-scoped route 404s (`workspace_not_found`) while `get_workspace_context`-based routes
    (decisions, conversations) still answer 200 — which is a confusing combination to debug.
  - **`scripts/restore.sh` cannot run inside the api container** (it shells out to
    `docker compose exec`, DB22). The automated backup/restore round trip therefore exercises the
    layer *below* the script: a real `pg_dump` through `create_pre_migration_backup`, then
    `psql -v ON_ERROR_STOP=1` against the same database URL the script would use, comparing table
    counts and upload files. The host-side `make backup`/`make restore` path stays quickstart
    Section 5's job and T070's CI job.
  - Docs rule that keeps paying for itself: check every command, env var, and endpoint in a new doc
    against `Makefile`, `compose.yaml`'s `api` environment block, `.env.example`, and the router
    before writing it. `CHUNKING_PROFILE_PRESET`/`RETRIEVAL_UNIT_STRATEGY` are forwarded by
    compose; `max_ingestion_attempts`/`max_evaluation_attempts` are not (so they are `Settings`
    fields, not `.env` knobs).
- [M-063] Iteration 67 (two defects, one human-reported, one found by the batch's own full-suite
  gate):
  - **A rolled-back rebuild must not claim progress it discarded.** `dispatch.py`'s
    `RebuildAborted` branch commits `documents_completed: 0` with `failed`. The progress hook
    commits each document's completion during the run (DB41), so without this a failed row read
    `failed 4/7` while DB43 had rolled all four back — a stored falsehood, not just cosmetics.
    `documents_total` still describes the real snapshot; "aborted after N documents" belongs in
    `error` if anything ever needs it.
  - **Focused runs cannot see state-dependent HTTP assertions.** T027's first-status check passed
    in isolation (the rebuild row was already committed by the first poll) and failed in the full
    suite, where the first poll lands in the 404 window (`not_started`). Rule: filter the window
    entries out of "the rebuild's first status" claims, but keep them in the failure message, and
    never assume the dispatch task has run before the first poll.
  - **Fixtures that must produce a *staged* failure need distinct content.** Identical content is
    an `embedding_cache` hit, so the embedding provider is never called for the second document
    and the staged failure never fires; the abort fixture's two documents therefore differ.
- [M-064] Iteration 68 (DB44, checker V122): **one definition of a `failed` row.**
  `dispatch.py`'s `_failed_fields(...)` builds the fields every failure path writes, including
  `documents_completed: 0`. Three paths call it — `RebuildAborted`, the generic
  `except Exception`, and `mark_interrupted_rebuilds`. Adding a fourth path means calling the
  helper, never hand-building the dict; iteration 67's mistake was fixing one of three paths.
  Test shape worth reusing: instead of *asserting* the rolled-back count is 0 (which passes
  trivially if no progress was ever committed), the abort test now holds the rebuild inside the
  second document's embedding, reads the row from another session at `running 1/2`, and only then
  lets it fail — that pins the intermediate state the `0` is supposed to contradict.
- [M-065] Iteration 69 (DB45 + T032): the rebuild banner and the isolation footgun.
  - The banner lives in `web/src/components/CorpusRebuildBanner.tsx`, polls via
    `getCorpusRebuild()`, and treats any error with `status < 500` as "nothing to show" — in
    particular 404 `corpus_rebuild_not_found` means no rebuild has ever run, which is the normal
    state, not a failure. It resumes polling after a retry rather than trusting the retry's own
    response, because the row is the source of truth.
  - Component tests must not depend on `instanceof <ApiClientError>`, and page tests must mock new
    client calls: `Workspace.test.tsx` mocks `../api/client` with a factory, so an unmocked export
    is `undefined` and an `instanceof` check throws *from inside the catch block*. The banner's
    status check is duck-typed for that reason, and `Workspace.test.tsx` now defaults
    `getCorpusRebuild` to a 404 rejection.
  - **Never hand-type a Docker Compose command in this repo without `-p`** (DB46). `compose.yaml`
    pins `name: decision-assistant`, so `docker compose run --rm web npm run build` — the command
    AGENTS.md documents for the web build — targets the *real* project, starts its `db`/`api`, and
    lets the app auto-migrate the real dev database. The Makefile targets pass `-p` for this
    reason; the documented bare command does not. Always add
    `-p decision-assistant-test` (and `WEB_BUILD_TARGET=build` for anything needing npm).
- [M-066] Iteration 70 (D8's host-side half): **the backup/restore scripts can be tested from the
  host, and the three variables that make it safe are the whole trick.** `make test-backup` runs
  `scripts/test_backup_restore.sh`, which exports `COMPOSE_PROJECT_NAME=<project>-backup` (the
  scripts call bare `docker compose`, and `compose.yaml` pins `name: decision-assistant`),
  redirects `BACKUP_DIR` into its temp dir (a fresh database makes the api's startup path take a
  pre-migration backup, and that archive must not land in the repo's `./backups`), and overrides
  `API_PORT` (a live dev stack commonly holds 8000). It then asserts row counts for `workspaces`
  and `decisions` plus one upload file, and fails if the wipe did not change the counts — a no-op
  restore must not pass. Division of labour with `api/tests/integration/test_backup_restore.py`:
  that file covers everything *below* the scripts (pg_dump, archive layout, psql restore, every
  table), this one covers the scripts themselves, which shell out to `docker compose exec` and so
  cannot run inside the api container (DB22).
- [M-067] Iterations 71-73 (T066, lint enablement, T070): three lessons worth keeping.
  - **A lint "unused import" in a test module can be a pytest fixture re-export.**
    `from tests.support.document_fixtures import documents_api` exists so the module's tests can
    request that fixture; ruff reports it as F401 (unused) *and* F811 (every test's parameter of
    the same name "redefines" it). Removing it — the obvious "fix" — silently broke 14 tests with
    `fixture 'documents_api' not found`. The working combination is the explicit re-export alias
    (`import documents_api as documents_api`, which documents intent) **plus** a per-file ignore:
    `[tool.ruff.lint.per-file-ignores] "tests/**" = ["F811"]` in `api/pyproject.toml`. General
    rule: a lint fix must be validated by the suite, never by the linter alone.
  - **`[tool.ruff]` config lives in `api/pyproject.toml`, the linter itself does not.** Adding the
    config is free; adding the dependency is the human decision recorded in DB47. The CI job
    installs `ruff==0.13.2` itself, so the shipped and test images are unaffected.
  - When deciding *whether* a repo can afford a new gate, measure first: ruff found 32 findings
    (4 in `src`, 28 in `tests`) and was green after one pass, while `mypy
    --ignore-missing-imports src/decision_assistant` reports 103 errors unconfigured — that
    difference is what makes one a two-line change and the other a project.
- [M-068] Iteration 73 (T070): `.github/workflows/ci.yml`'s shape.
  - Four jobs: `lint` (ruff, pinned, installed by the job), `api-tests` (`make test-api` — builds
    the Docling image, so a 45-minute timeout), `web-tests` (`make test-web` + the `tsc -b`
    production build), `migration-check`.
  - The migration job uses a **`pgvector/pgvector:pg16` service container and host Python**
    (`pip install ./api`) rather than Docker-in-Docker: the same server image the app pins, no
    nested daemon, and a fast failure. It asserts `alembic current` contains `(head)` and then
    downgrades and re-upgrades the newest revision, which plain `upgrade head` cannot prove.
  - Every compose command inside CI carries `-p decision-assistant-test` for the DB46 reason.
  - Deliberately absent (and recorded in the workflow header + DB47): an API typecheck and a web
    lint, because neither tool exists yet. A `continue-on-error` job would report a green check
    that checks nothing.
- [M-069] Iteration 74 (DB48, the human's finding #2): **`func.now()` is the transaction timestamp,
  so a table-wide rewrite inside one transaction erases every row's `created_at` at once.**
  - The rebuild deletes and re-creates each `Document` with its id preserved, all inside one
    transaction; `created_at` is a `server_default`, so every re-created row got the same `now()`.
    `ORDER BY created_at DESC` then had nothing left to sort by, and the document list came back in
    plan order. The lesson generalises: any `ORDER BY` on a `server_default` timestamp needs a
    tiebreaker *and* the writers need to carry the value forward when they re-create rows.
  - Fix shape: capture the value in the snapshot (`DocumentSnapshot.created_at`), write it onto the
    re-created row, and add `id DESC` as the tiebreaker in `list_documents` — the shape the
    `IngestionJob` query in that same file already used.
  - Ordering the snapshot query matters for a second reason: it had no `ORDER BY`, so the
    re-ingestion sequence, the progress numbering and which document the row calls
    `documents_completed: 1` were all up to the planner. Matching `list_documents`'s order makes
    the progress a person reads match the list a person sees.
  - **Prove a regression test discriminates**: `cp -R api/src /tmp/neg`, revert the change there,
    mount that copy, and watch the test fail with the expected message. Two passes and no
    assertions about *why* it fails is the difference between coverage and a green light. Both new
    tests here were run that way (2 failed against the reverted copy, 2 passed against the tree).
- [M-070] Iteration 75 (DB47 option (a) + DB46 close-out): **one pin, three consumers, no repeat.**
  - The linter's version now exists in exactly one place (`api/pyproject.toml`'s `dev` extra). The
    `test` Dockerfile stage installs it, `make lint-api` runs it in that image, and the CI job
    extracts the pin with `grep -o 'ruff==[0-9.]*' | head -1` (failing loudly if absent) rather than
    restating it. A version written twice is a version that drifts.
  - Deliberately **not** `pip install ./api[dev]` in the lint job: that resolves the project's
    runtime dependencies, which here means Docling and torch — gigabytes for a ten-minute lint run.
    Install the one pin; get the rest from the image when you actually need the app.
  - Cost to expect: `dev` extras live in `pyproject.toml`, and the Dockerfile keys its dependency
    layer on `COPY pyproject.toml`, so *any* edit to that file — even a test-only extra —
    invalidates the layer and re-runs the Docling model download (DB35; ~10 minutes observed). Once
    per change, then cached.
  - Housekeeping is part of the record: DB46's stray archive was deleted at the human's direction
    (`backups/` empty) and the debt row moved to `resolved` with a sign-off-log line, because a
    human-directed action is still an action that needs to be traceable.
  - `make lint-api` uses `--no-deps`: linting needs no database, so it must not start one.
- [M-071] Iteration 76 (D13, option (d)): **amend the criterion, not the code — and make the
  amendment harder to pass, not easier.**
  - The defect was the maker's reading, not the workflow. D13 said "lint, typecheck, …", and the
    maker silently expanded "typecheck" into "an API static type check" — an expectation the
    criterion never expressed. The workflow already ran a real typecheck (`tsc -b` in the
    `web-tests` job; `make test-web` alone is vitest only and does not typecheck).
  - When a criterion's wording is the problem, the *criterion's check column* is where to compensate:
    the amended version demands the checker confirm each named check maps to a real job, which is
    stricter than the sentence it replaced. Freedom in the claim, rigour in the verification.
  - Record an amendment in every place the old wording was read: the criterion, the task, the debt
    row, and the artifact itself (here the workflow's header comment). A scope decision written in
    one file is a scope decision that will be rediscovered as a bug.
  - Attribute it: the human chose (d) after being shown both readings. A maker amending its own
    criterion to match its own implementation is the failure mode this avoids.
- [M-072] Iteration 77 (DB49): **a staged-failure test must not depend on which document the
  snapshot picks first — and a green run alone does not prove a flake is fixed.**
  - `_resolve_embedding_cache` (`ingestion/service.py`) asks the provider only for hashes it is
    missing, and `truncate_corpus_derived_tables` deletes `embedding_cache` up front. So the first
    document re-embeds and repopulates the cache, and any later document whose chunk text is
    byte-identical is served *entirely* from that cache: a provider that counts `embed` calls to
    stage a failure never reaches its second call. DB48's `created_at DESC, id DESC` ordering turned
    that latent coupling into a ~50% flake (documents seeded in one transaction share `created_at`,
    so random uuids decide the order).
  - Fixture rule: two documents in one rebuild test must share no chunk *content* — differing is not
    enough. Superset fixtures (`SOURCE_TEXT + extra`) are the trap, because the shared first chunk
    is exactly what gets cached.
  - Verification shape that settled it: 14 consecutive passes of the fixed test against 2-of-2
    failures of the deliberately reverted fixture. Both directions are required; one green run is
    only a lucky order.
  - `api/tests/support/corpus_rebuild_fixtures.py` now holds the two source documents plus
    `OutageEmbeddingProvider`/`rebuild_providers`, following DB30's `document_fixtures.py` precedent.
    The extraction was not cosmetic: with a 12-line fixture, `test_corpus_rebuild_abort.py` at 486
    lines had no room for the fixture *and* the comment that stops the regression returning.
  - Six other test files sit over the 500-line cap (DB53); treat the cap as unenforced for tests, and
    budget for a `tests/support/` extraction whenever one of them is touched.
- [M-073] Iteration 78 (DB50, human chose option (a)): **"in the passage" is not "in the evidence" — an
  explicit value must be grounded in the verified quote span.**
  - `AnswerVerifier` had two tiers of rigour: citations are span-exact (`content_hash` +
    `content[start:end] == quote`), but `_verify_explicit_values` searched the cited passage's **whole
    content**. Any text sharing a passage with a real quote — including injected instruction text —
    could ground a fabricated date or entity. The fix collects the quotes that actually verified, per
    passage, and matches against those only. Scope is unchanged (still the claim's own `passage_ids`),
    so it is a narrow change: same search target, stricter corpus.
  - A "must reject" test of this kind must assert its own trap (`value in content` **and**
    `value not in quote`), or it passes for the wrong reason once the passage stops containing the value.
  - `git checkout -- api/src/.../verifier.py` is a clean mutant baseline here (the file's only
    working-tree change is the fix itself), and a src-only edit rebuilds in ~14 s.
  - The integration test is the one that captures FR-023/D12, and under the mutant it failed on
    `injection-adversarial.md` **only**: the clean fixture already abstained, so the injected text was
    literally what changed the verifier's outcome. `assert value not in SHARED_QUOTE` plus
    `assert (value in passage.content) == (fixture is adversarial)` encodes exactly that asymmetry.
  - `ANSWER_SYSTEM_INSTRUCTION` never asks the model to populate `explicit_dates`/`explicit_entities`;
    they ride along in the schema. So tightening them has a small expected abstention impact, and the
    DB50 gap was correspondingly mostly latent — worth deciding separately whether those fields should
    be prompted for at all, or dropped.
  - Environment: the human's `docker system prune` cleared the build cache, so the next api build was a
    full ~10 min rebuild (apt + deps + Docling models) although no Dockerfile input changed; src-only
    rebuilds were back to ~14 s immediately afterwards. Verify *before* assuming a 6-second rebuild —
    a pruned cache looks exactly like a Dockerfile regression.

- [M-074] Iteration 79 (T038, D1): **the backup/restore operator doc, and where its facts live.**
  `docs/backup-restore.md` is new; `docs/install.md` links it and no longer points at the unbuilt
  `docs/providers.md` (T053 is still `[ ]`, so that reference was a dead link, the same class V80
  failed).
  - Primary sources for every claim, so the next doc task can reuse them: `Makefile` (`backup`
    delegates `scripts/backup.sh "$(BACKUP_DIR)"` with `BACKUP_DIR ?= backups`; `restore` needs
    `-- <file>` and exits 2 with `Usage: make restore -- <backup-file>` when bare), `scripts/backup.sh`
    / `scripts/restore.sh` (archive = `database.sql` from `pg_dump --clean --if-exists` + `uploads.tar`;
    `POSTGRES_USER`/`POSTGRES_DB` default to `decision_assistant` and are read from the environment,
    never `.env`), `api/src/decision_assistant/backup.py` + `config.py` (pre-migration archives use the
    `decision-assistant-premigration-backup-` prefix, `backup_directory` `/workspace/backups`,
    `PRE_MIGRATION_BACKUP_RETENTION` default 5, kept separate from `make backup` archives so rotation
    cannot delete a user's backup), `compose.yaml:45,92` (`BACKUP_DIRECTORY` env vs the
    `${BACKUP_DIR:-./backups}:/workspace/backups` bind — two different names for two different things),
    `.gitignore:15` (`backups/`).
  - DB51/DB52 became documented operator steps, not fixes: restart `api` after a restore (stale pooled
    connection/type OIDs), uploads extraction is additive, and a customized `POSTGRES_USER`/`POSTGRES_DB`
    must be exported for the scripts. A doc that documents a residual must not promise the ideal
    ("byte-identical volume") — that is how V123 failed T033.
  - `make -n <target>` is the cheap check that a doc's command transcription is right without running a
    destructive flow; docs-only iterations legitimately skip `make test-api`/`make test-web` (no code
    touched, no image rebuild).

- [M-075] Iteration 80 (T054+T056, US7 logging): **log scrubbing needs two layers, and root is not
  enough.**
  - A filter that rewrites the record's own fields (`msg`, tuple/dict `args`, `exc_text`,
    `stack_info`) cannot see a traceback: `exc_info` is only turned into text by the formatter. So
    scrubbing must ALSO override `Formatter.formatMessage`/`formatException`/`formatStack`. Proved
    by mutant: deleting the `formatException` override fails exactly the traceback test and nothing
    else, i.e. the two layers are independently load-bearing. Scrub only those three parts, not the
    whole formatted line, or the logger name gets redacted whenever it contains a configured secret
    value (which happens for real: the shared placeholder password is `decision_assistant`).
  - `logging.getLogger()` (root) alone misses uvicorn's logs: uvicorn gives `uvicorn.error` and
    `uvicorn.access` their own handlers with `propagate = False`. Attach the file handler to root
    plus `uvicorn`, `uvicorn.error`, `uvicorn.access`.
  - Idempotent install: mark the handler (`handler._decision_assistant_file_handler = True`) and on
    re-configure remove+close only marked handlers. `create_app` runs many times in tests;
    unmarked handlers belong to pytest/uvicorn and must survive. Closing the handler while it is
    still attached elsewhere would break the other logger, so detach from every target before
    closing.
  - Scrub **by value, not by shape**: every non-empty configured secret (gemini key, JWT secret,
    bootstrap password, and the password parsed out of `DATABASE_URL` via `make_url`) with no
    minimum length; replace longest-first so a secret containing another is replaced whole.
    `make_url` can raise on a malformed URL — catch it, because a bad `DATABASE_URL` is
    `validate_startup_config`'s problem and must not stop logging from being configured.
  - Configure logging in `create_app`, not `lifespan`: a failure inside `lifespan` then lands in the
    log file too. `_startup_logger` stays on `uvicorn.error` because `docker compose logs` reads
    stdout/stderr and quickstart.md Section 3 greps it.
  - Cheap mutation recipe used here (repo untouched): `docker compose ... run --rm -T api sh -c
    "sed -i 's/…/…/' src/decision_assistant/<file>.py && grep -c … && pytest <file> -q"`.
  - Environment: this session's sync terminal tool intermittently returned empty output and once
    truncated a live `make test-api` log at 6%; long gates were re-run with output redirected to
    `tmp/*.log` and read back from the file. Treat a short/truncated gate log as a failed run, not
    a pass, and delete the temp logs before handoff.

- [M-076] Iteration 81 (T048, provider disclosure): **the disclosure's facts, and two terminal traps.**
  - Put the two disclosed facts in one place (`providers/disclosure.py`): `active_provider` = the
    generation provider (it is what turns document text into answers), and
    `sends_document_text_remotely` = True unless *every* configured provider is in
    `OFFLINE_PROVIDERS = {"ollama"}`. A mixed config (local generation, remote embedding) must read as
    remote — documents get embedded too — and an unknown provider name fails toward disclosing more.
    The response still names only the generation provider, so the UI work (T051) has to state the
    embedding provider as well or it under-discloses.
  - Acknowledgement is idempotent and keeps the **first** timestamp: re-stamping answers "the user
    hit the button", not "the user accepted". Both routes are owner-scoped through
    `service.get(workspace_id, owner_user_id=user.id)`; the write path needs the same filter as the
    read path, or one user could satisfy the FR-014 guard on another user's workspace.
  - Terminal trap 1: `while pgrep -f 'make test-api'; do sleep 5; done` **never exits** — the waiter's
    own command line contains the pattern, so it matches itself. Wait on the log instead
    (`while ! grep -q MAKE_EXIT tmp/<gate>.log; do sleep 10; done`).
  - Terminal trap 2: `make test-api > file` buffers through a pipe, so the log can sit at ~5 KB for
    minutes while the run is healthy. Confirm liveness with `pgrep -fl 'run --rm api pytest'` and
    `docker compose -p decision-assistant-test ps`, not with the file size.
  - The T049 upload guard is deliberately its own increment: it changes every existing upload path
    (16 test call sites across 3 files, plus `scripts/ingest_corpus.py`'s documented corpus-reset
    upload), so the plan is fixture-level acknowledgement plus a new test file driving the gate
    through the real route.

- [M-077] Iteration 82 (T055+T057, diagnostics bundle): **an allowlist alone is not enough for a dump.**
  - `BUNDLE_SETTINGS_FIELDS` names what may ship, but the fields that actually carry credentials here
    are plain strings (`database_url`, `ollama_base_url`), so an allowlist mistake leaks silently. The
    bundle therefore has three independent guards: the allowlist, a name rule
    (`secret|password|api_key|token|url` → refused even if listed), and a scalar-only value filter (a
    `SecretStr` is not a JSON scalar). Every guard must fail before a secret ships.
  - Write leak tests so a failure **names the leaking field**. The first version asserted through the
    assembled zip, so the mutant's real failure was `KeyError: 'settings.json'` (the dump had become
    unserializable) — it proved nothing about the guard it was supposed to cover. Asserting on
    `sanitized_settings(...)` directly gave exact attribution.
  - Split pure from impure: `assemble_bundle(settings, *, database_revision=...)` is testable with no
    database; `build_bundle(settings)` is the async entry point. `migrations.current_db_revision` is
    now public so the bundle reports the revision the app acts on instead of shelling out to the
    `alembic` CLI inside a request path.
  - Log files are globbed as `<LOG_FILE_NAME>*` from `log_directory`, so rotated `.1`, `.2` siblings
    come along and a missing directory yields a valid bundle rather than an exception.
  - Environment: the same gate took 207 s at iteration 82 versus 156 s at iteration 81 with no relevant
    code change — an unrelated `underwriteflow-*` stack is running on this machine. Check `pgrep`/`docker
    ps` before suspecting a code-caused slowdown; the pipe-buffered log sits at 6-15% for minutes.

- [M-078] Iteration 83 (T061+T063+T064, upload validation): **a stand-in for `Settings` must carry every
  field the callee reads.**
  - `_parse_for_ingestion` now reads `settings.max_pdf_pages`; two `test_pdf_parser.py` tests stub
    `get_settings` with `SimpleNamespace(model_timeout_seconds=...)`, so the batch gate went red with
    `AttributeError` in one test and an `AssertionError` in the other — one missing field, two different
    symptoms. Grep for `SimpleNamespace(` near `get_settings` before adding a Settings read to a
    function that tests drive directly.
  - Validation design: PDF `%PDF-`, docx zip header, text = UTF-8 + no NUL in the first 8 KB; page
    count via `pypdfium2` (already a dependency, no new one). Codes are the existing
    `DocumentParseError`s (`content_type_mismatch`, `pdf_page_limit_exceeded`) — sanitized, non-retryable.
    An unreadable PDF is left to the parser on purpose: otherwise a pdfium limitation becomes a
    permanent "invalid file" verdict for the user.
  - It sits in `ingestion/service.py` before `parse_document` (whose signature is frozen by AGENTS.md),
    not inside the parser — so `scripts/ingest_corpus.py`, the retry endpoint and corpus-rebuild
    re-ingestion all get it for free through the same service path.
  - Consequence to remember: a mislabelled file is rejected on the *ingestion* path, so the upload still
    returns 202 and the job fails with the sanitized code; and a legacy corpus containing such a file can
    now abort a rebuild (safe — DB43 rolls back — but the rebuild cannot finish).
  - Gradient that keeps paying off: run focused → mutants → full gate. Here the full gate caught what
    focused tests could not, and the mutants gave per-check attribution that the focused run alone did
    not (magic off → 4 fail; page limit off → exactly 1 fail).

- [M-079] Iteration 84 (DB55, checker V136): **a probe that reads a fixed window must not demand a
  complete unit inside that window.**
  - Strict decoding of the first 8 KB rejects any file whose multi-byte character straddles the
    boundary — a permanent, non-retryable false positive on real prose (em dashes, smart quotes,
    accents, CJK). Fix: read `_PROBE_BYTES + 1` bytes, and decode with
    `codecs.getincrementaldecoder("utf-8")().decode(head[:_PROBE_BYTES], final=len(head) <= _PROBE_BYTES)`.
    The completeness flag is what keeps the check honest: a file smaller than the probe still gets a
    `final=True` decode, so a truncated trailing character is still refused.
  - Assertion: `len(head) <= _PROBE_BYTES` (not `<`), because reading exactly `_PROBE_BYTES` bytes means
    the whole file was read.
  - A checker probe is worth reproducing as a repo test verbatim (V136's 8191 ASCII bytes + em dash,
    for both text suffixes). The mutant that reverts to `final=True` then fails exactly that test,
    which is the evidence that the new test is load-bearing rather than decorative.
  - DB56 stays open and is two unrelated things in one row: exact-match-only secret scrubbing (a D10
    live-check item) and pdfium page counting running synchronously inside the async ingestion path
    (a small `asyncio.to_thread` fix, deliberately not bundled into the DB55 change).

- [M-080] Iteration 85 (T046+T049, disclosure upload gate): **put the rule where every caller crosses,
  and do not override the dependency you are asserting on.**
  - FR-014's gate lives in `documents/service.py`'s `submit_uploads` (409
    `disclosure_not_acknowledged`), not in the router: the route is the only HTTP entry point, but the
    service is the only place every caller crosses. Same reasoning as M-078's placement choice for
    validation.
  - Adding a gate to the upload path touches every existing upload test plus both HTTP scripts. Do it
    by acknowledging in the shared fixture (`tests/support/document_fixtures.py`), in the vertical-slice
    fixture, and once in each script — `scripts/ingest_corpus.py` gained
    `_acknowledge_provider_disclosure` so the AGENTS.md corpus-reset flow keeps working, and
    `scripts/smoke.py` acks after binding its workspace.
  - Test smell found here: a non-owner test that overrides `get_workspace_context` is asserting on a
    dependency it just replaced. The stranger's upload reached the gate and got 409 (not 404) because
    ownership lives in the real dependency (`workspace/context.py` →
    `WorkspaceService.get(..., owner_user_id=user.id)`). Leave the real dependency in place when the
    point of the test is what it does.
  - Mutant recipe that worked: `sed -i 's/        if workspace.disclosure_acknowledged_at is None:/        if False:/'`
    → exactly the gate test fails, and its log shows the upload answering `202` without an
    acknowledgement.
  - Residual to flag to a human: the CLI acknowledging on the operator's behalf is a documented-flow
    convenience that technically satisfies a human step by script; a `--acknowledge-disclosure` flag
    would be the stricter shape.

- [M-081] Iteration 86 (T058+T060, diagnostics bundle route): **make the HTTP test read the real thing,
  and re-check the linter every time.**
  - The route test deliberately leaves `database_url` to the environment so `build_bundle` hits the
    real test database, then asserts `alembic-current.txt` is non-empty instead of pinning a revision
    number. Same file asserts none of the Gemini key, JWT secret or resolved DB password appear in the
    response bytes (`make_url(settings.database_url).password` gives the real value to search for).
  - Auth mutant recipe: `sed -i 's/Depends(get_current_user)/Depends(lambda: None)/'` on the router →
    exactly the 401 test fails, and the log shows an unauthenticated `200 OK`.
  - T060 ("confirm no telemetry") needed no code: the evidence is a grep —
    `grep -rniE "sentry|datadog|opentelemetry|prometheus|newrelic|posthog|statsig|segment\\.io|analytics|telemetry"`
    over both source trees and both dependency manifests → zero matches. Put that command in the task
    note so the next run can re-run it after any dependency change.
  - Linting the new test file is now a habit worth automating: an unused `pytest` import failed
    `make lint-api` here, the third time in three iterations (80, 81, 86) that a new test file shipped
    an unused import. `make lint-api` takes ~30 s and runs after `make test-api` anyway; the cheaper
    fix is to check imports before writing the file.

- [M-082] Iteration 87 (T062+T065, parse timeout): **the budget is read from the cached settings, not
  the object you passed, and an abandoned thread is the price of a bounded parse.**
  - `_parse_for_ingestion` calls `get_settings()` (cached, process-wide) for both `model_timeout_seconds`
    and `max_pdf_pages`. A test that constructs `Settings(model_timeout_seconds=0.2)` and hands it to
    `LocalIngestionDispatcher` changes nothing: patch `ingestion_service.get_settings` instead, or the
    test waits the real 120 s default.
  - Make a parse slow by patching `ingestion.service.parse_document` for the suffix under test (and
    delegating to the real parser otherwise). Patching the parser, not shipping a huge fixture, keeps
    the suite's runtime independent of Docling's speed while still exercising the real dispatcher,
    service, DB writes and error mapping.
  - `asyncio.wait_for(asyncio.to_thread(...))` cannot kill the worker thread: the timeout marks the job
    failed (sanitized `pdf_parse_timeout`, `retryable False`, `finished_at` set) while the thread keeps
    running to completion. FR-022's "cannot block ingestion indefinitely" holds because the loop moves
    on — and the test proves it by ingesting a second document to `completed` while the first thread is
    still sleeping.
  - Reusable fixtures for "run the real dispatch path" now live in `api/tests/support/ingestion_fixtures.py`
    (`FakeProviderBundleFactory`, `loop_local_dispatch_session_factory`, `cleanup_workspace`); the
    duplication with `test_ingestion_restart_recovery.py` was left in place deliberately rather than
    refactoring a verified file inside an unrelated increment.
  - Mutant: `sed -i 's/timeout=settings.model_timeout_seconds/timeout=3600/'` → the slow parse finishes
    and the test fails, which is what makes the timeout wiring load-bearing rather than incidental.

- [M-083] Iteration 88 (T059, web diagnostics download): **two jsdom traps, and where the TS typecheck
  actually runs.**
  - `make test-web` builds the `build` stage first, so `tsc -b && vite build` runs on every web change —
    a TypeScript error fails the *test* target, not just a build. Good: no separate typecheck step is
    needed for web work.
  - jsdom trap 1: `Blob` has no `.text()`; assert `blob.size` instead.
  - jsdom trap 2: `new Response(new Blob(["x"]))` is **stringified** by jsdom's Response, so the body
    reads back as `[object Blob]` (13 bytes). Mock fetch responses with a raw string or `Uint8Array`
    body.
  - Download mechanics for an authenticated file: `fetch` with the bearer header → `response.blob()` →
    `URL.createObjectURL` → temporary anchor click → `revokeObjectURL` on the next tick (revoking in the
    same task can cancel the download). `URL.createObjectURL` does not exist in jsdom, so tests
    `Object.defineProperty` it per test and restore afterwards.
  - A non-JSON response cannot go through `apiRequest` (it always parses JSON); the second such helper
    (`getHealth` was the first) is `downloadDiagnosticsBundle`, and both carry their own 401 handling.
    If a third appears, extract the shared fetch/error-mapping core instead of copying it a third time.

- [M-084] Iteration 89 (T050+T047, provider switch): **one process means one provider, and the test's
  monkeypatch target is the module the route imported from.**
  - The storage shape is the human's choice, not the maker's: a single global `app_settings` row
    (revision `0017_app_settings`, `CheckConstraint("id = 1")`) beats a per-workspace column because
    generation/embedding clients are process-wide. The mismatch that creates — a per-workspace route
    that dispatches a per-workspace rebuild while the change is global — is DB57, not something to
    paper over in the route.
  - Apply a stored configuration by **mutating** the `Settings` object the app already holds, in
    `lifespan` and before any provider/profile resolution. `app.state.settings` *is* that object, so a
    `model_copy` swap would leave every existing reference pointing at the old values.
  - Refuse a configuration the process cannot actually call (`validate_selected_provider_configuration`)
    before persisting it. Otherwise the failure surfaces later, as a rebuild that aborts after real
    work — DB43 rolls the whole corpus transaction back, so the operator pays for the discovery in
    lost time rather than in a 409.
  - The cached provider bundle is built from the settings current at construction time, so a switch
    must replace `app.state.provider_bundle_factory`; the superseded factory is `aclose()`d as a
    **background task** (after the response) because an in-flight request may still hold it.
  - Monkeypatch target: the route calls `dispatch_pending_rebuild` and `CachedProviderBundleFactory`
    *through `workspace.router`*, so patch `decision_assistant.workspace.router`, not the defining
    module (`workspace.rebuild.dispatch` / `providers.factory`) — patching the defining module leaves
    the route dispatching for real.
  - Falsify-the-gate mutant: `sed -i 's/profile_changed = proposed_profile != current_profile/profile_changed = False/'`
    on `workspace/router.py` (in a throwaway `run --rm` container, repo untouched) fails exactly the 3
    tests that depend on the gate and leaves the other 4 green — the attribution that makes the
    confirmation requirement load-bearing rather than incidentally satisfied.
  - A fresh-DB migration check is cheap and catches the silly failure mode: one `run --rm` with
    `alembic upgrade head && alembic current && alembic downgrade -1 && alembic upgrade head && alembic current`
    proves the new revision applies, reverses and re-applies. `make lint-api` tears the isolated
    project down with `-v` on its own, so the next command starts from a clean database.

- [M-085] Iteration 90 (T041+T040, first-run secrets): **the app cannot own the `.env` Compose reads,
  so split host-script from decision-module — and put every decision in Python.**
  - `compose.yaml` passes settings as explicit `environment:` entries substituted from the **host**
    repo-root `.env`; `api/Dockerfile`'s `WORKDIR` is `/workspace/api` with no `.env` in the image.
    So a container can never satisfy a task that says "the app writes `.env`" — and the only mount
    that would let it is the repo root, which D4 forbids. `scripts/setup.sh` owns the file; the
    module owns the decisions. Same host/in-container split already accepted for T037 (DB22).
  - Put *all* the logic in Python even when the entry point is a shell script: the script becomes
    text movement (`< .env > tmp`, assert the three keys came back, `mv`), and T040's uniqueness and
    no-secrets-in-logs tests have something to call. A shell-only generator would have been
    untestable.
  - Generate **hex**, not base64/urlsafe: the same value is written to a `.env` line, a `psql`
    literal for `ALTER ROLE`, and a URL password, and hex needs no escaping in any of the three. It
    also makes the script's one built SQL statement assertable before it is built
    (`^[0-9a-f]{64}$` for the password, a plain-identifier regex for the role name — AGENTS.md's
    no-interpolation rule, since `psql` takes no bind parameter for an identifier).
  - A `Mapping` in / `Mapping` out design pays off here: `update_env_text` preserves comments,
    ordering and unowned keys, `parse_env_text` is a plain line parser, and the only impure step is
    the host `mv`. It also made the DB26 case expressible — a `DATABASE_URL` whose password was
    rotated by hand must be left alone rather than "fixed" to match `POSTGRES_PASSWORD`.
  - **Report what you did not change.** The first focused run failed because
    `apply_first_run_setup` forwarded `overwrite=True` and therefore always returned
    `skipped=()`, so the operator could not tell a no-op `make setup` from a rotation. Fixed with an
    explicit `keep` collection; the regression is asserted in both directions (mixed-case
    `applied`/`skipped`, and all-kept on a second run).
  - One source of truth for a security constant: `config.PLACEHOLDER_DB_CREDENTIALS` is now public so
    setup and `validate_startup_config` cannot drift apart — duplicating `"decision_assistant"` in
    the setup module would have been the classic way this gets out of sync.
  - pytest replaces `sys.stdin` with a reader that raises while output is captured, so any CLI test
    that reads stdin must `monkeypatch.setattr("sys.stdin", io.StringIO(...))`.
  - Deliberately not done: running `make setup` against the real stack (it rewrites the real `.env`
    and rotates the real database password). The script's orchestration is therefore unproven live
    — say so rather than implying the gate covered it.

- [M-086] Iteration 91 (T042+T043+T039, first-run password flow): **removing a startup path means
  hunting every reference, not just its caller; and an unauthenticated route is safe only if the
  service refuses the second call.**
  - Deleting the env bootstrap touched far more than `main.py`: `Settings` fields, `compose.yaml`,
    `.env.example`, the log-scrubbing secret list, the bundle test's adversarial allowlist, and the
    allowlists' expected sets. `grep -rn` for the *field names* before starting is what kept this
    from being a five-file surprise; 19 dead references came out of six test files.
  - `extra="ignore"` means removing a `Settings` field silently swallows it, so a stale `.env` entry
    fails quietly instead of erroring. If the field's absence matters (here it does — it was a
    credential), assert `not hasattr(settings, ...)` so a resurrection is caught.
  - The first-run route carries **no** JWT dependency by design, so the guard has to live in the
    service: `create_password` takes the same advisory lock the old bootstrap used and raises 409 if
    any user exists. The mutation that proves the guard is load-bearing is deleting that raise inside
    a throwaway container — it fails exactly two tests (HTTP and service level) and errors a third as
    collateral.
  - Moving workspace adoption (unowned `Workspace` rows) from startup into `create_password` is what
    keeps a pre-existing install accessible after the flow change; without it, the new password would
    own no data. The old code's semantics are worth preserving even when its entry point is deleted.
  - When a task says "keep X but make it local-only", check whether X is *already* local-only before
    writing anything. The password-reset path here was already recovery-code based, so the honest
    move was recording that and changing nothing.
  - Deliberately not done: `make setup` and quickstart §2 were still never executed against a stack,
    so D9's live evidence does not exist — the quickstart was rewritten to be executable, which is a
    different thing from having been executed.

- [M-087] Iteration 92 (T044, web first-run screen): **a two-step flow must not let its own gate
  unmount the second step — and `App` owning its router changes how tests render it.**
  - The bug the test caught: creating the password set `needs_password_setup: false` in the setup
    context, the shell's gate re-read it, and the recovery-code step unmounted the moment it appeared
    — destroying the only recovery code the install will ever have. Any state that a *gate* reads must
    not be updated until the flow that gate is protecting has finished. Fix + reason live at the call
    site in `SetupContext`.
  - The same test also showed the correct failure direction for a status probe: unknown → show the
    ordinary sign-in form, never block. A first-run gate that fails closed would lock out installs
    that already work.
  - `App` contains its own `BrowserRouter`, so tests must render `<App/>` directly — wrapping it in
    `MemoryRouter` makes React Router throw, and the `ApiErrorBoundary` renders "Something interrupted
    this view", which hides the cause. When a web test fails with that panel, read the boundary input,
    not the rendered text.
  - Adding a gate to the shell breaks every existing test that asserts the first screen: `App.test.tsx`
    now has to answer the probe and `await findByRole`, not `getByRole`. Budget for that whenever a
    new provider or fetch lands in `App`.
  - `make test-web` runs `tsc -b` in its build stage, so a TypeScript error in new web code fails the
    *test* target — no separate typecheck step is needed (same lesson as M-083).
  - When an increment changes an API file for comments only, run `make test-api` anyway and say so:
    the identical count (510) is then evidence about the change ("comment-only, as expected") rather
    than an unexplained number.

- [M-084] Iteration 93 (DB60/D11, killable PDF parse): **a thread cannot be cancelled, a process can,
  and the timeout is only real if the memory dies with it.**
  - `asyncio.wait_for(asyncio.to_thread(...))` abandons a thread, not the work: V139 measured ~5 cores
    and ~2 GiB held for minutes after the job read `failed`, and 14 of those OOM-killed the API. The
    fix is a child process (`multiprocessing.get_context("spawn")`, one `Pipe`, `kill()` + `join()`),
    not a shorter budget.
  - `spawn` (not `fork`) because the parent holds a live event loop and an asyncpg pool; the cost is
    one Docling model load per PDF, accepted so a kill discards the converter instead of leaving a
    half-initialised one behind.
  - Bound the *number* of children, not only the time: `parse_slots(limit)` is a process-wide
    `threading.BoundedSemaphore` (default 1). Acquire it **before** starting the child, release in a
    `finally`, or one slow PDF wedges every later parse (the timeout test releases its slot on
    purpose).

- [M-089] Iteration 94 (T051/T052/T067, US6 web + provider failure states): **the UI half of an
  enforced rule, and three traps that cost a web-test cycle each.**
  - The disclosure gate is a *nicety*, not the guard: `submit_uploads` already refuses with 409
    `disclosure_not_acknowledged`. So the screen is written to **fail closed** (an unreadable
    disclosure hides the library rather than offering an upload that will be refused) and it gates
    only the source-library page, not the shell.
  - A component that fetches on mount breaks every test that renders its parent synchronously.
    `Workspace.test.tsx`'s polling cases install `vi.useFakeTimers()` *before* rendering, and RTL's
    `waitFor` then waits on a timer that never runs → the test hangs to its 5 s timeout. Flush the
    resolved promise with `await act(async () => {})` (twice) instead of `findBy*`.
  - Mocking a module with a partial factory (`vi.mock("../api/client", () => ({ ... }))`) makes every
    export it does not list `undefined`. `x instanceof ApiClientError` against that binding **throws**
    rather than returning false, so a shared helper should read `error.code` structurally when it may
    run under such a mock.
  - `vi.clearAllMocks()` does not clear a queued `mockResolvedValueOnce`: a test that fails early
    leaks its queued value into the next test. Use `vi.resetAllMocks()` when each test sets its own
    implementations.
  - Keep `web/src/api/client.ts` from growing past the 500-line cap: new API surfaces get their own
    module (`web/src/api/provider.ts`), and `projectPath` is exported so they can reuse the
    active-workspace guard instead of copying it.

- [M-090] Iteration 94 (T068/T069/T071, release process + docs): **a required changelog line is worth
  a test, and an unset shell variable is not an empty grep pattern.**
  - FR-025's `Corpus rebuild on upgrade: yes|no — <why>` line is asserted by
    `api/tests/unit/test_release_version.py` (semver, both versions equal, an entry per version, the
    rebuild line present *and* reasoned) rather than trusted, and repeated in
    `.github/workflows/release.yml` because a tag can land on a commit whose tests never ran. The
    example heading in the format docs uses `[X.Y.Z]` so the parser does not mistake it for a
    release.
  - The test reads `web/package.json` and `CHANGELOG.md`, which live outside the `api` build context:
    add them to `compose.test.yml`'s read-only mounts, the same way `scripts/` and `evaluation/`
    work. A test that reads a repo-root path must be mounted or it fails only in the container.
  - `grep -iF "$GEMINI_API_KEY"` with the variable unset is `grep -F ""`, which matches **every**
    line — a leak check that always reports a leak. Read values out of `.env` with
    `sed -n 's/^KEY=//p' .env | tail -n 1` and skip empty ones.
  - Same trap in docs commands: `${OLLAMA_GENERATION_MODEL:-qwen3:8b}` does **not** read `.env`, so a
    copy-pasteable command silently pulls the default model. Prefer literal names plus a sentence
    about which `.env` key they must match.
  - The child must send a sanitized `(code, message)` pair, never an exception object, and the parent
    must treat anything else in the pipe as `pdf_parse_failed`. The parent's copy of the write end
    needs an explicit `close()` or `poll()` never sees EOF when the child dies without sending.
  - A parser patched in-process cannot cross a process boundary: the old `test_pdf_parser.py`
    `monkeypatch.setattr(service, "parse_document", ...)` pattern for making a parse slow no longer
    reaches the code under test. Get a timeout from a tiny budget against a **real** fixture instead,
    and prove the kill with `multiprocessing.active_children()` (children are children of the pytest
    process, so the assertion is visible there).
  - The parse budget is now its own setting (`pdf_parse_timeout_seconds`); any place that used
    `MODEL_TIMEOUT_SECONDS` to force a parse timeout — including quickstart §6 — has to move, or the
    operator's command stops exercising the timeout it documents.
- [M-091] Iteration 95 (T051 fix, checker-fail V146): **one "is anything remote?" flag cannot name the
  destination.** The disclosure needs the per-provider split, not just the aggregate.
  - `sends_document_text_remotely` (any provider remote) was correct as a *summary* but wrong as a
    *destination*: with `GENERATION_PROVIDER=ollama` + `EMBEDDING_PROVIDER=gemini`, the UI said text
    went "to ollama's service", when the embeddings (the search index) actually go to Gemini. The
    disclosure response now carries `generation_provider`/`embedding_provider` and
    `generation_sends_document_text_remotely`/`embedding_sends_document_text_remotely`, and the UI
    renders two fact rows (search index = embedding provider, answers = generation provider).
  - Keep the old `provider` and `sends_document_text_remotely` fields alongside the new ones: several
    web test suites and `ProviderSettings` consumed them, and the contract lists them. Additive beats
    replacing.
  - A per-name remote check (`provider_is_remote`) extracted from the aggregate function avoids a
    second source of truth for "which names are offline"; the aggregate folds over it.
  - When a provider name now appears in two places on one screen, `getByText("gemini")` matches both
    and throws — assert on the full sentence (`/the search index is built by/`) or use `getAllByText`
    with a length, not a bare `getByText` of the name.
- [M-092] Iteration 96 (T072, the live quickstart pass): **a clean checkout is a copy, not a worktree,
  and isolation is an env var.**
  - `git worktree add` cannot carry ~96 iterations of uncommitted work (HEAD predates them). For T072,
    rsync the working tree to a throwaway dir excluding `.git`, `.env`, `backups/`, `uploads/`, `tmp/`,
    tooling dirs and `node_modules` — that yields a checkout with no `.env`, which is the quickstart
    prerequisite `make setup` exercises.
  - `COMPOSE_PROJECT_NAME=decision-assistant-qs` (exported) overrides the pinned `name:
    decision-assistant` in `compose.yaml`, so every bare `make`/`docker compose` quickstart command
    targets the throwaway project. Verified: rendered `docker compose config --format json`'s `name`
    field becomes `decision-assistant-qs`. Real image IDs confirmed unchanged after the run.
  - The production api image has **no** `/workspace/scripts` or `/workspace/sample_data` (repo-root
    paths outside the `api` build context), so AGENTS.md's documented corpus-reset `ingest_corpus.py`
    container form is stale. Seed via the host: `INGEST_API_ORIGIN=http://127.0.0.1:8000
    INGEST_USERNAME=... INGEST_PASSWORD=... python3 scripts/ingest_corpus.py --source-directory
    sample_data/atlas --workspace-name Atlas`.
  - After `make setup`, `.env` has a blank `GEMINI_API_KEY`; copy the real key in with
    `grep '^GEMINI_API_KEY=' <real .env> | (sed -i '' '/^GEMINI_API_KEY=/d' .env; cat >> .env)` so
    live ingestion/answering works — never print the value.
  - A tiny PDF ingests in ~3 s on this machine, so a §3 kill at +3 s can land *after* completion. Use a
    slow OCR fixture (`scanned-english.pdf`) and kill at ~2 s; the restart log line
    `startup recovery: requeued 1 ingestion job(s)` is the proof the kill landed mid-run.
  - The §6 `.md`/`.docx` upload needs `;type=text/markdown` (or the docx MIME) or curl sends
    `application/octet-stream` and the upload is rejected `unsupported_media_type`.
  - Residue worth remembering: a daemonic child is terminated on a normal exit but reparented if the
    API is SIGKILLed, `spawn` costs a model load per PDF, and the slot is taken before the budget
    starts, so a queue of slow PDFs delays the newest upload. **The last of those is superseded by
    M-096**: the slot wait is now bounded and the child watches its parent.

- [M-093] Iteration 97 (DB51/DB52/DB64/DB66): **the restore script fixes its own aftermath, and the
  scripts read the same `.env` Compose does.**
  - DB51's stale-OID 500 is fixed in the script, not the docs: `restore.sh` restarts `api` at the end
    when `docker compose ps -q api` shows it running. `restart` (not `up --force-recreate`) is enough —
    the pooled asyncpg connections die with the process.
  - DB52: `POSTGRES_USER`/`POSTGRES_DB` are read from the repo-root `.env` with `sed -n
    's/^<KEY>=//p' | tail -n 1` plus quote-stripping; the shell environment wins over `.env`, and the
    shipped default is last. Never `source` that file — it holds real secrets.
  - DB52: clearing the uploads directory uses `docker compose exec -T api sh -lc 'find
    /workspace/uploads -mindepth 1 -delete'`. `findutils` is Essential in Debian, so `find` exists in
    `python:3.12-slim`, and `-mindepth 1` keeps the mount point itself.
  - A script-only fix still needs a regression assertion: `scripts/test_backup_restore.sh` now plants a
    stray upload *after* the backup and fails if it survives the restore, and requires `GET /health` to
    answer 200 afterwards (DB51's symptom is a 500 on the first request after a restore).
  - **`docker compose up` builds only when the image is missing**, so a gate that never says `build`
    can test a stale image and report a product failure that no longer exists in the source. That
    happened here: `decision-assistant-test-backup-api:latest` was 25 hours old and died on
    `_bootstrap_credentials`, a startup check iteration 91 had deleted. `scripts/test_backup_restore.sh`
    now runs `docker compose -p "$PROJECT" build api` before `up`, the same shape as
    `make test-api`/`test-web`. When a long-lived per-project image exists, check its age
    (`docker image ls --format '{{.Repository}} {{.CreatedSince}}'`) before believing a red gate.
  - DB64/DB66 were doc-versus-reality mismatches: `web_node_modules` was an undeclared volume named in
    four docs (uninstall, AGENTS.md, README, profile-benchmark) and is now gone from all four; §6's
    "every rejection carries `retryable: false`" is narrowed to the job-level codes, because the
    upload-level `file_too_large` refusal is produced before a job exists and carries no `retryable`.

- [M-094] Iteration 98 (DB57/DB65, human-directed): **one global provider row means the guards and the
  consequences are global too.**
  - Keep the per-workspace route, but (a) refuse a switch while **any** workspace has a rebuild
    `pending`/`running` — `has_active_rebuild(session, workspace_id)` became
    `active_rebuild_workspace_ids(session)` — and (b) put a per-workspace breakdown in the 409 preview.
    That breakdown is scoped to the caller's own workspaces: the stored configuration is global, but a
    preview must not disclose another user's workspace names.
  - Move the guard **before** `store_provider_config`/`apply_stored_provider_config`. It used to run
    after applying them, so a 409 left the in-process `Settings` mutated while the row rolled back.
  - Deliberately remaining: the confirmed switch still dispatches a rebuild for the addressed workspace
    only; the others re-ingest through `corpus_reset_required` on their next readiness check, and a
    restart is the quickest way to run that check for all of them. Documented in `docs/providers.md`.
  - DB65 clears `disclosure_acknowledged_at` on **every** workspace, because the setting is
    process-wide, and only on a false→true `sends_document_text_remotely` transition. The switch
    response gained `disclosure_acknowledgement_cleared` and the 409 preview
    `disclosure_acknowledgement_will_be_cleared`, so the UI can say uploads are blocked again.
  - Python trap worth never repeating: a method named `list` on a class shadows the builtin for later
    **annotations in that class body** (annotations are evaluated while the class is created, and the
    class namespace is the lookup scope), so `-> list[tuple[Workspace, int]]` after `async def
    list(...)` raised `TypeError: 'function' object is not subscriptable` at import — 45 collection
    errors from one annotation. Quote the annotation, or add `from __future__ import annotations`.

- [M-095] Iteration 99 (DB56/DB61): **scrub the encodings, and stop the duplicate log line at its
  source.**
  - DB56: `scrub_values(settings)` widens the scrub set to the percent-encoded form, the base64 form
    and the URL userinfo (`user:password`, and the password alone, from `database_url` and
    `ollama_base_url`) of every configured secret. `secret_values()` stays the raw list so its existing
    tests keep their meaning; `configure_logging` now uses `scrub_values`. The username is deliberately
    left alone — it is not a secret, and redacting it only makes logs harder to read.
  - DB61(b): `uvicorn.error` has **no handlers and `propagate` true**, so attaching the file handler to
    it *and* to `uvicorn` wrote every startup line and traceback twice. `_LOG_TARGETS` is now
    `("", "uvicorn", "uvicorn.access")`, and `uvicorn`/`uvicorn.access` get `propagate = False`
    enforced. uvicorn's own config already sets that, so production behaviour is unchanged; stating it
    explicitly is what makes the line count identical under pytest, where uvicorn never configured
    logging.
  - DB61(a): `/workspace/logs` is now the named volume `api_logs`, or a container recreate deletes the
    history the bundle exists to ship.
  - DB61(c): `ingestion/service.py` logs one warning per failure carrying the code, the ids and the
    exception **type** only — never the message, which can quote document text and would then travel
    inside a bundle a user attaches to a bug report.
  - DB61(d): `build_bundle` catches a failed `current_db_revision` and reports `unavailable (database
    unreachable)` instead of a 500, because a half-down stack is exactly when the bundle is wanted.

- [M-096] Iteration 100 (DB63): **bound the queue wait, and let the child notice a dead parent.**
  - The slot is still acquired before the budget starts, but `run_parse_in_subprocess` now waits at
    most `max(600s, 20 × timeout)` for it (`_QUEUE_WAIT_FLOOR_SECONDS`/`_QUEUE_WAIT_MULTIPLE`) and
    raises the existing `ParseTimeoutError`, so a document queued behind an unbounded backlog fails
    with the documented `pdf_parse_timeout` code instead of holding an executor thread for minutes. The
    multiple and the floor are deliberately generous: the trailing document in checker V143's
    14-slow-PDF repro waited roughly fourteen budgets and must still parse.
  - `queue_wait_seconds` is injectable, which is what makes the cap testable in 0.05 s rather than ten
    minutes; the ingestion service passes nothing and gets the computed default.
  - The child now runs a watchdog thread that exits hard once `os.getppid()` stops matching the pid
    that spawned it. Compose's namespace teardown already covers the container case; this closes the
    host-run orphan. `daemon=True` is not a substitute — it only fires on a clean parent exit.
  - Still accepted: `spawn` costs a Docling model load per PDF, and a kill skips Docling's own cleanup.

- [M-097] Iteration 101 (DB53): **split test files by moving scaffolding to `tests/support/` with line
  ranges, then let ruff find the import drift.**
  - All six oversized files are now under the cap. Three needed only an extraction of their scaffolding
    (`test_ingestion_service.py`, `test_decisions_api.py`, `test_schema.py`); three needed an
    extraction *and* a thematic test split (`test_hybrid_retrieval.py` → corpus retrieval plus
    decision/trace; `test_gemini_provider.py` → embedding plus generation; `test_evaluation_runs.py` →
    runner plus HTTP surface). New support modules: `ingestion_service_fixtures`,
    `decision_api_fixtures`, `retrieval_fixtures`, `gemini_fakes`, `evaluation_run_fixtures`.
  - The mechanics that made this cheap and reviewable: `sed -n 'A,Bp' > support/x.py` for the moved
    block, `head -n N`/`sed -i '' 'A,Bd'` to shrink the original, and a hand-written import prologue per
    file. **No test body was retyped**, so the diff is movement plus imports.
  - `grep` first, split second: proving no other module imported these helpers is what made
    `tests/support/<name>_fixtures.py` safe rather than a rewrite of every caller.
  - Never guess which imports survive — `grep -c` counts are wrong for `asyncio` and `date` (they match
    `@pytest.mark.asyncio` and `document_date=`). Ruff's F401 found the five real leftovers in one pass.
  - A fixture re-exported from a support module must be aliased on import
    (`from tests.support.x import y as y`) because the suite runs `--import-mode=importlib`.
- [M-098] Splitting a module that other code imports: put the *shared leaf* first. Moving
  `IngestionError` into `ingestion/errors.py` (and `DocumentApiError` into `documents/errors.py`) is
  what lets the extracted modules raise the same errors without importing the service back — the
  service re-imports the name, so no existing `from …service import X` breaks. Same rule on the web
  side for the opposite reason: `client.ts` re-exports the transport names from `transport.ts`
  because TypeScript re-exports cannot create the circular import DB12 was avoiding, and that keeps
  ~20 call sites untouched. Check where the *state* lives before splitting a client: the token and
  active-workspace variables had to move with `apiRequest`, so callers that read them directly
  (`downloadDiagnosticsBundle`, `uploadDocuments`) now use `getAccessToken`/`handleUnauthorized`/
  `projectPath` instead. (iteration 102, DB67)
- [M-099] A regression test for a stale-pool bug must assert on the pool, not only on the response.
  DB51's symptom (a 500 on the first request after a restore) could not be reproduced in the backup
  test's environment at all: with `restore.sh`'s restart removed, `/api/v1/setup/status`,
  `/api/v1/workspaces`, `/ready` and `/health` all answered exactly as before, because the failure
  needs a statement whose parameters carry a *custom* type OID (pgvector's `vector`), which an empty
  unauthenticated test database never creates. What does discriminate, deterministically, is the
  connection set: snapshot `pg_stat_activity` pids (`pid <> pg_backend_pid() and backend_type =
  'client backend'`) after warming the pool, then require that none of them is still connected once
  the restore returns. Warm the pool *before* the backup or the snapshot is empty and asserts
  nothing. (iteration 102, DB69; residual recorded as DB71)
- [M-100] A guard that only some routes take is half a guard — test the *call site*, not just the
  primitive. DB68's fix added `acquire_provider_switch_lock` and a test that proves the advisory
  lock blocks a second session, but nothing proved any route called it: deleting the call from
  `workspace/router.py` left every test green. Both routes that write a `pending` `CorpusRebuild`
  (the provider switch and the manual retry) now have a route-level test asserting the lock is taken
  with the request's own session, and the mutant that removes both calls fails exactly those two
  tests while the primitive test still passes. Two Makefile lessons from the same iteration: (1) a
  recipe line that must run even when an earlier line fails has to be in the *same* shell invocation
  (`cmd1 \\ && cmd2; ret=$$?; cleanup; exit $$ret`), because separate recipe lines stop at the first
  failure; (2) when several `make` targets share one `-p` Compose project, running two of them
  concurrently tears down each other's network (`down -v` removes it) and the suite fails with
  `socket.gaierror: Name or service not known` — that is a harness collision, not a code defect.
  (iteration 103, DB72)
- [M-101] Taking a lock is not enough; **anything the route resolved before the lock is stale**.
  `Depends(...)` parameters are resolved before the route body runs, so
  `retry_corpus_rebuild`'s `provider_factory` was fetched *before* `acquire_provider_switch_lock`
  and a retry queued behind a confirmed switch dispatched the rebuild with the bundle the switch had
  already superseded and closed (V173). The same applies to `settings` — which is why the switch
  mutates it in place and the retry reads it after the lock. Rule: inside a route that serialises on
  a lock, read every mutable piece of app state (factory, settings) *after* acquiring it, and
  re-run every precondition check under it, because the check that ran before describes a world the
  request may have left. Two corollaries from the same iteration: (1) `functools`-style "delete the
  fix" mutants are impossible once the stale read is *removed* rather than reordered — the mutant has
  to re-introduce the pre-lock capture by hand; (2) a helper shared by the pre-lock and under-lock
  checks (`_require_failed_rebuild`) is what stops the 404/409 exits from drifting apart.
  (iteration 104, DB72a/DB73)
- [M-102] Never put `$!` in a shell command on this host: zsh's history expansion eats the closing
  quote of the `echo "started pid=$!"` line, leaving the persistent terminal stuck at `dquote>`.
  Every later command is then appended to that unterminated quote and silently never runs (the tool
  reports `Command produced no output`), which cost iteration 104 several confusing minutes and two
  accidentally-concurrent `make test-api` runs. Also: a `docker compose run` container outlives a
  killed terminal and keeps holding the isolated database, so the replacement run blocks — check
  `docker ps` for stray `api-run` containers before re-running. (iteration 104)
