# Loop Contract

## Purpose
1. Drive every task in `specs/002-production-readiness/tasks.md` (T001–T072) to completion,
   phase by phase, until the feature satisfies its spec.md success criteria and quickstart.md's
   8 validation scenarios all pass against the real stack.

## Done-criteria
| ID | Criterion (checkable) | How the checker verifies it | Status |
|----|-----------------------|-----------------------------|--------|
| D1 | All tasks T001–T072 in tasks.md marked `[X]` | Grep tasks.md for remaining `- [ ]` — zero matches | checker-pass (V167, 2026-09-27: re-check after iteration 102 holds.) Earlier: checker-pass (V159, 2026-09-27: re-check after iterations 97-101 holds.) Earlier: checker-pass (V153-V155, 2026-09-26, fresh-session checker: 0 unchecked tasks; the V146 mixed-configuration break no longer reproduces live; T072 independently re-run on a clean checkout, §1-§7 hold, §8 is process-only. The re-run contradicts one maker claim: DB51's post-restore 500 still reproduces (2 of 2).) Earlier: pending (iteration 96, 2026-09-26: **T072 executed** — quickstart.md all 8 sections run live against an isolated clean checkout (`decision-assistant-qs`, real project untouched). `grep -c '^- \[ \]' tasks.md` = **0**, so D1's literal check now passes; awaiting checker to re-verify T051 (V146 break) and confirm the T072 live run. Earlier: iteration 95, 2026-09-26: **T051 fixed** — the disclosure now reports both providers (`generation_provider`, `embedding_provider`) plus per-provider remote flags, and a mixed-configuration test pins the correct destination; maker-ready, awaiting checker re-verification of the V146 break. `make test-web` 78 passed, `make test-api` 529 passed, `make lint-api` clean, web build clean.) Earlier: pending (checker V146-V152, 2026-09-26: of iteration 94's 7 tasks, **T051 checker-fail** — the disclosure names the generation provider as where uploaded text goes, which is wrong for mixed configurations (ollama generation + gemini embedding says text is sent to ollama's service); T052, T053, T067, T068, T069, T071 checker-pass (T071 low confidence: never run on a runner). T072 still open. D1 cannot pass until T051 is fixed and T072 is done.) Earlier: pending (iteration 94: **7 of the 8 remaining tasks are done** — T051 (the web disclosure screen that gates the source library), T052 (the provider-switch confirmation dialog), T053 (`docs/providers.md`), T067 (provider failure states on the answering, ingestion and switch paths), T068 (SemVer plus a `CHANGELOG.md` whose every entry must state its corpus-rebuild impact, enforced by a new test rather than by prose), T069 (`docs/uninstall.md` + `docs/troubleshooting.md`), and T071 (`.github/workflows/release.yml`). The unchecked list is now exactly **T072** — the end-to-end quickstart pass against a clean checkout, which is the one task that cannot be done from this tree (it already has a `.env`) and which the human deferred the live `make setup` run to. Evidence: `make test-web` 18 files / 77 passed, `make test-api` 1 failed → 529 passed with the failure being my own new test (fixed and re-run), `make lint-api` exit 0. Maker belief only; nothing here has been checker-verified since V135. Earlier: iteration 92: **T044** (US5's last task) — the web first-run screen (`FirstRunSetup.tsx` + `SetupContext.tsx`), with `App.tsx` now gated on `GET /api/v1/setup/status` and falling back to sign-in when the probe fails. US5 is code-complete. 5 new tests plus 2 adapted `App.test.tsx` cases let the gate catch **a real bug in my own gate** — clearing `needs_password_setup` after the POST re-evaluated the gate and unmounted the recovery-code step, which in production would have destroyed the only recovery code the operator ever sees. `make test-web` → 15 files, **64 passed**; `make test-api` → **510 passed, 4 deselected** (run because an API file changed, comment-only). **D9 stays `pending`**: it needs the live quickstart §2 run, and `make setup` has still never been executed (deferred to T072 by the human). The 8 remaining unchecked tasks are T051-T053 (US6) and T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 91: **T042 + T043 + T039** (US5 backend complete) — the env bootstrap is gone (`BootstrapService.ensure_user` → `SetupService`, `main.py` no longer creates a user at startup, so a fresh install serves with no user at all), `GET /api/v1/setup/status` and `POST /api/v1/setup/password` exist without a JWT, and `auth_bootstrap_*` was removed from `Settings`/`compose.yaml`/`.env.example`/the secret set plus 19 dead references in six test files. 7 new integration tests + 3 T039 cases; mutant deleting the 409 check fails exactly the 2 tests that assert it; literal `make test-api` → **510 passed, 4 deselected**, exit 0; `make lint-api` exit 0. **D9 is closer but stays `pending`**: T044 (web first-run screen) remains, and neither `make setup` nor quickstart Section 2 has been run live. The 11 remaining unchecked tasks are T044 (US5), T051-T053 (US6) and T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 90: **T041 + T040** (US5 first-run secrets) — `make setup` now generates `AUTH_JWT_SECRET`, `POSTGRES_PASSWORD` and the `DATABASE_URL` that carries it into `.env`, then rotates the role password on the running database. The task's "`.env` the app manages" is infeasible in this deployment and the human chose the T037-style host-script + in-container-module split instead (**DB58**, resolved); 14 new tests; mutation (deterministic generator) fails exactly the 2 randomness-dependent tests; literal `make test-api` → **501 passed, 4 deselected**, exit 0. **D9 stays `pending`**: T039 and all of T042-T044 remain, and neither the setup script nor quickstart Section 2 has been run live. The 12 remaining unchecked tasks are T039, T042-T044 (US5), T051-T053 (US6) and T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 89: **T050 + T047** (US6 provider switch) — the provider choice is persisted in one global `app_settings` row (revision `0017_app_settings`) and re-applied over the environment defaults in `lifespan`, and `POST /api/v1/workspaces/{id}/provider` refuses a profile-affecting change with a 409 preview and no side effects until `confirm_rebuild: true`. 7 tests; mutant `profile_changed = False` fails exactly the 3 gate tests; literal `make test-api` → **487 passed, 4 deselected**, exit 0. D9 stayed `pending`. Earlier: iteration 88: T059 done — US7 complete, so **D10 is `maker-ready`** pending the checker's live quickstart Section 7 run (plus DB56's encoded-secret grep). The 16 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T047/T050-T053 (US6), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 87: T062 + T065 done — US8 complete, so **D11 is `maker-ready`** pending the checker's live quickstart Section 6 run. The 17 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T047/T050-T053 (US6), T059 (US7), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 86: T058 + T060 done — authenticated `GET /api/v1/diagnostics/bundle` (in-memory zip, download headers, 2 tests including a 401 case) and the zero-telemetry grep evidence recorded in T060. The 19 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T047/T050-T053 (US6), T059 (US7), T062/T065 (US8), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 85: T046 + T049 done — the FR-014 upload gate is enforced (`DisclosureNotAcknowledged`, 409, in `submit_uploads` so every caller is covered), with the shared fixtures and both HTTP scripts acknowledging first; 2 new tests, mutant attribution exact. The 21 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T047/T050-T053 (US6), T058-T060 (US7), T062/T065 (US8), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 84: **DB55 fixed** — the text probe now uses an incremental UTF-8 decoder with a completeness flag, so a valid non-ASCII file over 8 KB is no longer refused; the checker's V136 probe is now a repo regression test and reverting the fix fails exactly that test. Focused 24 passed, literal `make test-api` **475 passed, 4 deselected**, exit 0, `make lint-api` exit 0, real images unchanged. Awaiting checker re-verification. Still 23 tasks unticked: T039-T044 (US5), T046/T047/T049-T053 (US6), T058-T060 (US7), T062/T065 (US8), T067-T072 (Polish). Earlier: pending (checker V136, 2026-09-26: T063 is ticked but has a defect, DB55 (medium): valid UTF-8 text over 8 KB is rejected when byte 8192 splits a character. The maker should fix it before D11 is claimed. 23 tasks unticked.) Earlier: pending (iteration 83: T061 + T063 + T064 done — pre-parse content validation (`ingestion/validation.py`: PDF/docx magic bytes, UTF-8 text probe, `max_pdf_pages` via pypdfium2) wired into `_parse_for_ingestion` before the frozen `parse_document`, 8 tests, mutants attributed per check. The batch's own full gate caught a fixture regression (two `test_pdf_parser.py` Settings stubs missing the new field) which was fixed and re-run green. The 23 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T046/T047/T049-T053 (US6), T058-T060 (US7), T062/T065 (US8), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 82: T055 + T057 done — diagnostics bundle: `diagnostics/bundle.py` with an allowlist plus a credential-name guard plus a scalar-only value filter, pure `assemble_bundle`/async `build_bundle`, and a new public `migrations.current_db_revision`; 7 tests with per-test mutation attribution. The 26 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T046/T047/T049-T053 (US6), T058-T060 (US7), T061-T065 (US8), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 81: T048 done — provider disclosure is readable (`GET`) and acknowledgeable (`POST .../ack`), owner-scoped, backed by `providers/disclosure.py` and an idempotent `WorkspaceService.acknowledge_provider_disclosure`; 7 new tests, 5 of which fail under combined mutants. The upload guard T049 and its test T046 are deliberately next — T049 changes every existing upload path. The 28 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T046/T047/T049-T053 (US6), T055/T057-T060 (US7), T061-T065 (US8), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 80: T054 + T056 done — US7's rotating, secret-scrubbed file logging (`diagnostics/logging.py` + 4 `Settings` fields + `create_app` wiring, 9 tests, both mutation-checked). The 29 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T046-T053 (US6), T055/T057-T060 (US7), T061-T065 (US8), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 79: T038 written and `[X]` — new `docs/backup-restore.md` (110 lines), linked from `docs/install.md`'s new "Backup and restore" section. The 31 remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T046-T053 (US6), T054-T060 (US7), T061-T065 (US8), T067-T072 (Polish). D1 stays `pending`. Earlier: iteration 70: US3 is now complete on both sides — T026-T033 all `[X]`, T027 and T033 in iterations 64-65, T032 in iteration 69. Remaining unchecked tasks are Phases 7-11: T039-T044 (US5), T046-T053 (US6), T054-T060 (US7), T061-T065 (US8), T066-T072 (Polish). D1 stays `pending`) |
| D2 | `make test-api` exits 0 | Run the command against the branch's current state | checker-pass (V172, 2026-09-27: re-check after iteration 103 holds.) Earlier: checker-pass (V166, 2026-09-27: re-check after iteration 102 holds.) Earlier: checker-pass (V158, 2026-09-27: re-check after iterations 97-101 holds.) Earlier: checker-pass (V157, 2026-09-26: re-check after iteration 95, `make test-api` 529 passed, exit 0; lint clean.) Earlier: checker-pass (V145, 2026-09-26: re-check after iteration 94, `make test-api` 529 passed / `make test-web` 77 passed, both exit 0; `make lint-api` clean.) Earlier: checker-pass (V141, 2026-09-26: re-check after iterations 79-92, `make test-api TEST_PROJECT=checker93t` exit 0, 510 passed, 4 deselected.) Earlier: checker-pass (V131/V132, 2026-09-26: literal `make test-api TEST_PROJECT=checker78t` exit 0, 442 passed, 4 deselected; abort test 10/10 in isolation; DB49 fixture verified disjoint by reading.) Earlier: maker-ready (iteration 77, 2026-09-26: DB49 fixed — the abort fixture is now order-independent, so the run no longer depends on which document DB48's `created_at DESC, id DESC` snapshot picks first. The literal `make test-api` exits 0: `439 passed, 4 deselected, 15 warnings in 126.67s`. Evidence in both directions rather than one green run: **14 consecutive passes** of the abort test (8 before the fixture extraction, 6 after) against **2 of 2 failures** with the old superset fixture deliberately restored and the image rebuilt. No file under `api/src/` changed — the defect was the fixture. Maker belief only; the checker should confirm the *failure mode* is gone, not merely that the suite is green.) Earlier: checker-fail (V124/V125, 2026-09-26: the literal `make test-api TEST_PROJECT=checker77t` gave 1 failed and 438 passed, exit 2. `test_corpus_rebuild_abort.py::test_failed_rebuild_rolls_back_and_stays_retryable` is order-dependent after DB48's `created_at DESC, id DESC` snapshot ordering: when `second.md` is processed first, the embedding cache serves `meeting.md` and the outage never triggers. This is a test-fixture defect, not a product bug. See DB49.) Earlier: checker-pass (V121, 2026-09-26: literal `make test-api TEST_PROJECT=checker67t` on the working tree after iterations 64-67 exited 0 with 430 passed and 4 deselected; the project was torn down.) Earlier: checker-pass (V70, 2026-09-25: literal bare `make test-api` on `improvement` exit 0, 379 collected/4 deselected, now isolated via `-p decision-assistant-test`; real project unchanged.) Earlier: checker-pass (V34, 2026-09-25: literal `make test-api` in isolated `checker-i20` project on `1835e99`; `364 passed, 4 deselected` (live_provider default only), exit 0, after an environment-only disk-full blocker was cleared with user approval) |
| D3 | `make test-web` exits 0 | Run the command against the branch's current state | checker-pass (V172, 2026-09-27: re-check after iteration 103 holds.) Earlier: checker-pass (V166, 2026-09-27: re-check after iteration 102 holds.) Earlier: checker-pass (V158, 2026-09-27: re-check after iterations 97-101 holds.) Earlier: checker-pass (V157, 2026-09-26: re-check after iteration 95, `make test-web` 78 passed, exit 0.) Earlier: checker-pass (V145, 2026-09-26: re-check after iteration 94, `make test-api` 529 passed / `make test-web` 77 passed, both exit 0; `make lint-api` clean.) Earlier: checker-pass (V141, 2026-09-26: re-check after iterations 40-92, `make test-web TEST_PROJECT=checker93w` exit 0, 15 files, 64 passed.) Earlier: checker-pass (V70, 2026-09-25: literal bare `make test-web` on `improvement` exit 0, 38 passed (11 files); DB18/DB21 ported in place; real images/containers/volumes unchanged.) Earlier: maker-ready (iteration 39, 2026-09-25: fixed DB24 by hand-porting DB18/DB21's diffs directly onto `improvement` — `compose.yaml`'s `web` build gained `target: ${WEB_BUILD_TARGET:-runtime}`, `Makefile`'s `test-api`/`test-web` now isolate every `docker compose` call to `-p decision-assistant-test`. Live-verified with the LITERAL bare commands: `make test-api` exit 0, 377 passed; `make test-web` exit 0, 38 passed (11 files). Real `decision-assistant-{api,web}:latest` image IDs/timestamps confirmed unchanged before/after. Maker belief only — needs independent checker re-verification. See iterations.md Iteration 39.) Earlier: checker-fail (V69, 2026-09-25: on `improvement`, isolated `make test-web` → `npm: not found`, Error 127; DB18/DB21 fixes live only on unmerged `loop-iter-31` (DB24). Earlier V56/V57 pass was on that worktree, not this branch. Earlier: (V56/V57, 2026-09-25: independently ran the LITERAL, unmodified bare `make test-web` from worktree `loop-iter-31` at `7eb13f6` — not an isolated-project workaround, the actual documented command — exit 0, `38 passed (11 files), 0 failed`, built under isolated project `decision-assistant-test` per DB21's fix, not the real `decision-assistant` project. Also independently ran literal bare `make test-api`: exit 0, `368 passed, 4 deselected`, isolated project torn down cleanly. Confirmed via `docker images` before/after both runs that real `decision-assistant-api:latest`/`decision-assistant-web:latest` timestamps and image IDs were unchanged — the DB21 safety gap is closed, not just the DB18 mechanism. This is the first time D3 has been satisfied by the literal documented command itself.) |
| D4 | `docker compose config` shows no source bind-mounts for `api`/`web` and localhost-only (`127.0.0.1:`) port bindings for `api`, `web`, `ollama`, with no `db` port published | Run `docker compose config` and inspect `volumes:`/`ports:` output directly | checker-pass (V65, 2026-09-25: re-verified after iteration 37's `./backups` bind-mount — `api` volumes = `uploads_data` + data bind `./backups`, no source bind-mount on `api`/`web`; ports `127.0.0.1` for api/web/ollama; `db` unpublished. Earlier V58, 2026-09-25: independently ran `docker compose -p d4checkiter33 config` on `improvement` at `3e2f32f` directly, no worktree needed — confirmed `api`/`web` have no source bind-mounts (`api.volumes` is `uploads_data` named volume only, `web` has no `volumes:` key), `api`/`web` ports resolve `host_ip: 127.0.0.1`, `db` has zero `ports:` entries. Separately ran with `--profile ollama` since it is profile-gated and does not render by default: confirmed `ollama.ports` also resolves `host_ip: 127.0.0.1`. Checked `.env` for a local override that could mask the result first — none found. Isolated project torn down after.) |
| D5 | `docker compose run --rm api alembic upgrade head && alembic current` succeeds against a fresh DB | Run the command; confirm exit 0 and `current` shows the latest revision | checker-pass (V12, 2026-09-24: ran literally via `docker compose -p checker-d5 run --rm api alembic upgrade head && alembic current` against an isolated fresh DB; exit 0 both times, full 0001→0012 chain applied, `alembic current` reports `0012_production_readiness (head)`; isolated project/volumes torn down afterward) |
| D6 | quickstart.md Section 3 (ingestion survives interruption): a job killed mid-run reaches a terminal state (`succeeded`/`failed`) without manual resubmission | Execute the quickstart.md Section 3 steps against a running stack | checker-pass (V101, 2026-09-25: independent live run on isolated `checker55`, with kills confirmed mid-transaction. SIGKILL mid-run recovered to `completed` with 1 job and the same passage count as an uninterrupted baseline. A graceful `restart` drains the job to `completed`. 4 mid-run kills ended in a terminal `failed` `ingestion_interrupted`. The evaluation half returns 503 `evaluation_unavailable` per DB32. See DB33 for the quickstart timing wording.) Earlier: maker-ready (iteration 54, 2026-09-25: executed live against an isolated production stack — `docker compose kill api` (SIGKILL) 8 s after upload, `up -d api --wait`, then `GET /documents/{id}` went `pending` → `pending` → `completed` (progress 100) with **no** manual resubmission; container log shows `startup recovery: requeued 1 ingestion job(s) (1 dispatched), marked 0 failed`; DB shows exactly one `ingestion_jobs` row, `completed`, `attempt_count 1`, `started_at`/`finished_at` set. Iteration 54 also added that log line, which the quickstart's `grep -i "recover\|requeue"` step assumed but the app never emitted (no logging configured anywhere). Caveat for the checker: the quickstart's "repeat for an evaluation run" line is not executable in the production stack — see DB32. Maker belief only.) |
| D7 | quickstart.md Section 4 (upgrade/corpus rebuild): decisions/conversations remain readable and unchanged throughout a forced `corpus_reset_required` rebuild | Execute quickstart.md Section 4 steps; diff decision/conversation API responses before vs. during rebuild | checker-pass (V121, 2026-09-26: re-checked after iteration 67 changed the abort path. 430 passed in-suite, including T027's `test_upgrade_rebuild_flow.py`, and the `RebuildAborted` row now commits `documents_completed: 0`. The residual in V122/DB44 (low) is that the generic-failure and startup-sweep paths still keep stale progress; this is not a D7 blocker. V123/DB45 (low): `docs/upgrade.md` claims a web banner that T032 has not built.) Earlier: checker-pass (V119/V120, 2026-09-26, independent checker on iteration 63. `make test-api TEST_PROJECT=checker63t`: 428 passed. Live isolated `checker63`: a rebuild with an invalid provider key ended `failed 0/6` with the corpus, the documents, and 18/18 decision/evidence links unchanged, and a byte-identical API diff. `/ready` returned 503 via `CorpusResetRequired`. A partial abort after 4/6 re-ingested documents rolled back whole. The HTTP retry after the fix reached `completed 6/6` with the same 18 decisions, no duplicates, and 18/18 valid quote offsets. Per-document retry returns 409 after an abort, so no duplicate path remains. T027/T032/T033 stay open under D1.) Earlier: maker-ready (iteration 63, 2026-09-26: DB43 fixed per the human's option A — a per-document re-ingestion failure now raises `RebuildAborted` inside the still-open corpus transaction, `dispatch._run` rolls that transaction back and only then commits `failed` + the offending document's error code onto the `CorpusRebuild` row (separate session, DB41), so the workspace keeps the corpus and the decision/evidence links it had before the attempt and T030's retry re-runs against real data instead of `completed 0/0`. Maker belief only — the checker must re-run V118's failure path live against quickstart.md Section 4, and should also verify the new claim that `/ready` reports not-ready after an aborted rebuild. Earlier: checker-fail (V113-V118, 2026-09-26, checker on iteration 62). All three V109/V110/V112 failures are fixed and verified live on the real upgrade path, `0015 -> 0016` plus backup plus rebuild: in-flight reads unchanged (V113), progress visible (V114), reshaped chunks re-linked with valid quote offsets and timelines kept (V115), failed documents preserved with no rebuild loop (V116), SIGKILL recovery (V117). New blocker V118/DB43 (high): a rebuild that fails partway (provider outage) commits the truncation, so the corpus is emptied and 20/20 decisions are unlinked. Rebuild retry then returns `completed 0/0`, and per-document retry duplicates decisions. Earlier: maker-ready (iteration 62, 2026-09-26: the three counts V109/V110/V112 failed are believed fixed — DB40 (stored quote + quote-text re-link, and the readers serve it), DB41 (progress row committed before the work and per-update, plus a startup sweep of interrupted rows), DB42 (documents without an active version preserved). Maker belief only, **not** checker-verified: T027's HTTP lifecycle test is still unwritten, and the checker should run quickstart.md Section 4 live rather than trust this record. Earlier: checker-fail (V108-V112, 2026-09-26, checker on iteration 61). Live isolated `checker61` run. The core claim holds: every decision, conversation, and history read stayed byte-identical and returned 200 throughout a rebuild (V108). The rebuild still fails D7 on three counts. (1) V109: a preset change that reshapes chunks (ordinary 4-section doc, 9 to 5 passages) drops 4/4 of that doc's decisions from `GET /timelines` and nulls their evidence `quote` (DB40 residual, now confirmed live). (2) V110: `GET .../corpus-rebuild` returns 404, or the previous run's `completed` row, for the whole running rebuild, because the rebuild is one transaction (new DB41). (3) V112: documents with failed ingestion are deleted by the rebuild (new DB42). Mid-rebuild SIGKILL recovers cleanly (V111). Earlier: maker-ready (iteration 61, 2026-09-26): T028-T031 implemented — `run_corpus_rebuild` snapshots pre-truncate, truncates, redispatches ingestion with decision-extraction skipped (new `extract_decisions` flag), and re-links decisions/evidence to the new rows (exact for `document_version_id`, content-hash-matched for `passage_id`, else `citation_stale=true`); `main.py` lifespan dispatches it per `corpus_reset_required` workspace (T029); `GET`/`POST .../corpus-rebuild/retry` endpoints added (T030). `pytest -q -m "not live_provider"` 422 passed (twice). Also fixed loop debt DB39 (migration fails on pre-existing orphaned decisions) and DB40 (rebuilt decisions dropped from timelines/retrieval/answering — now partially resolved, see debt.md). **Not checker-verified**: T027's actual integration test (poll `GET /workspace/{id}/corpus-rebuild` through `pending → running → completed` against a real restart) is still unwritten, and DB40's residual reshaped-chunking case is untested live. See iterations.md Iteration 61. |
| D8 | quickstart.md Section 5 (backup/restore): data matches before backup and after restore | Execute quickstart.md Section 5 steps; compare row/file counts | checker-pass (V168, 2026-09-27: re-check after iteration 102 holds; the restart-removed mutant now fails the harness.) Earlier: checker-pass (V160, 2026-09-27: re-check after iterations 97-101 holds.) Earlier: checker-pass (V129, 2026-09-26: an independent operator run of quickstart Section 5 on the isolated `checker77b` stack with real Atlas data. After backup, down (no `-v`), up, a deliberate mutation, and `make restore`, all 20 tables were identical by row md5, the upload files were identical, and the API state was byte-identical. Residuals, not blockers: V130/DB51 (medium), the first request after restore returns 500 on stale asyncpg type OIDs; DB52 (low), restore leaves stray upload files, and the scripts ignore `.env` DB names.) Earlier: maker-ready (iteration 70, 2026-09-26: automation now exists on both sides of the script boundary — `api/tests/integration/test_backup_restore.py` (T034, iteration 66) covers everything below `scripts/backup.sh`/`scripts/restore.sh` (a real `pg_dump` through `create_pre_migration_backup`, the archive layout, the `psql -v ON_ERROR_STOP=1` restore, every application table's count), and the new `make test-backup` (iteration 70) covers the scripts themselves from the host: seed → `scripts/backup.sh` → wipe → `scripts/restore.sh` → counts and upload file must match, in an isolated project with `COMPOSE_PROJECT_NAME`/`BACKUP_DIR`/`API_PORT` redirected. Maker belief only — the criterion is the *operator's* run of quickstart.md Section 5 against a real stack, which only the checker can execute) |
| D9 | quickstart.md Section 2 (first-run setup + disclosure): no shared-default secret in `.env`, password-setup and provider-disclosure screens gate access/upload | Execute quickstart.md Section 2 steps | checker-pass (V156, 2026-09-26, medium confidence: live §2 on a clean checkout. Secrets generated (64 chars, mode 600, not the example values), setup idempotent, 5 concurrent password POSTs give exactly one 200, 422/409 enforced, disclosure gate 409 before ack and per workspace, cross-user ack 404, blank secret refuses start. The web screens were checked only through `make test-web`. New debt DB65 (low).) Earlier: pending (iteration 94: **the code half is complete; what is left is a live run and nothing else.** T051's disclosure screen (gating the source library) and T044's create-password screen both exist, and `quickstart.md` §2 no longer claims either is "still being built". Grading note unchanged (human-decided 2026-09-26, DB59): grade the flow, not an authority claim the design does not make — `needs_password_setup`/`POST /setup/password` are a first-run flow, `/auth/signup` is unauthenticated too, and what bounds the stack is the `127.0.0.1`-only binding (D4's superset). What *is* enforced server-side and should be checked as such: the 409 on a second `POST /password`, the 422 on a short password, and the disclosure gate refusing uploads with 409 `disclosure_not_acknowledged` until acknowledged. Still outstanding: `make setup` has never been executed, and no section of the quickstart has been run against a stack — both deferred by the human to T072 (sign-off log). **The maker cannot close D9 without doing exactly what the human deferred**, so it stays `pending`, not `maker-ready`. Earlier: iteration 92: **both first-run screens' code now exists** — T044's create-password screen (the last US5 task) and the disclosure half from iteration 85/89. What this criterion still lacks is entirely a **live run**: `make setup` has never been executed (human-deferred to T072, sign-off log) and no section of this quickstart has been run against a stack. Grading note (human-decided 2026-09-26, DB59): grade the flow, not an authority claim the design does not make. `needs_password_setup` / `POST /setup/password` are a first-run flow, not access control — `/auth/signup` is unauthenticated too, and what bounds the stack is the `127.0.0.1`-only port binding (D4's superset). The quickstart, `docs/install.md` and `auth/router.py` now say so explicitly. The parts that *are* enforced server-side and should be checked as such: the 409 on a second `POST /password`, the 422 on a short password, and the disclosure gate refusing uploads with 409 until acknowledged. Still missing before this section can run: T044 (web first-run screen) — and no live run of `make setup` or §2 has happened yet (deferred to T072 by the human on 2026-09-26, see the sign-off log). Earlier: iteration 90: the first half of the secret half exists — `make setup` generates `AUTH_JWT_SECRET`/`POSTGRES_PASSWORD`/`DATABASE_URL` and rotates the role password (T041/T040, DB58) — but `AUTH_BOOTSTRAP_*` env credentials were then still the only way to create the first login. 
| D10 | quickstart.md Section 7 (diagnostics bundle): zero secret values present in generated bundle | Execute quickstart.md Section 7 steps; grep bundle contents for configured secret values | checker-pass (V140, 2026-09-26, medium confidence: a live quickstart Section 7 run on isolated `checker93` with awkward secrets (a percent-encoded DB password, Ollama userinfo credentials). The bundle had 0 hits for 13 raw and derived secret forms, including after a DB-outage traceback storm. Auth is enforced (401 with no token or a bad token). DB56 is not exercised live; see DB61/DB62.) Earlier: maker-ready (iteration 88, maker's own view, **not** a verdict: every US7 task is done — T054/T056 in iteration 80 (rotating, secret-scrubbed logs), T055/T057 in 82 (bundle assembly, allowlist + two leak guards), T058/T060 in 86 (authenticated route, no-telemetry grep) and T059 here (web download action). Unit/integration evidence: the archive contains no configured secret value, the route requires auth, and both `make test-api` (480 passed, 4 deselected) and `make test-web` (59 passed) are green. A checker must run quickstart.md Section 7 live and grep the downloaded bundle — and, per DB56, should also grep for **encoded/derived** secret forms (a percent-encoded `DATABASE_URL` password, `OLLAMA_BASE_URL` userinfo), which value-based log scrubbing does not cover.) |
| D11 | quickstart.md Section 6 (upload safety): malformed/oversized/slow uploads rejected or bounded, worker recovers for next upload | Execute quickstart.md Section 6 steps | checker-pass (V142-V144, 2026-09-26, fresh-session checker: a live quickstart Section 6 run on isolated `checker94` shows mismatch, oversize and timeout each fail with their own non-retryable code, and the next upload completes. Break attempt: at a 25 s budget with 150-page PDFs, a timed-out parse drops from about 500% CPU and 3.2 GiB to idle and 170 MiB within one 4 s sample. V139's 14-slow-PDF repro peaks at 3.5 GiB, serialised, with no OOM and 0 restarts, and the trailing normal PDF completes. `.md` ingestion bypasses the PDF queue. Residuals are in DB63 (low); the section text still has 3 literal defects, see DB62.) Earlier: maker-ready (iteration 93, maker's own view, **not** a verdict: DB60 fixed. The parse runs in a killable child process (`ingestion/parse_runner.py`: `spawn`, a `Pipe` for the result, `kill()` + reap on timeout), so a timed-out parse no longer keeps a core and gigabytes of RSS alive — it is bounded by the new `pdf_parse_timeout_seconds` (default 120; the `MODEL_TIMEOUT_SECONDS` reuse is gone) and a process-wide slot pool sized by `pdf_parse_concurrency` (default 1), with `restart: unless-stopped` on `api` as the backstop. Evidence: a real `pdf/digital-english.pdf` parses in a child (`test_parse_runner.py`, 29 focused tests passed); a 10 ms budget kills the child and frees the slot; `test_parse_timeout_recovery.py` now asserts `multiprocessing.active_children()` holds no `docling-parse` child after a timed-out dispatch, which is V139's break turned into an assertion; literal `make test-api` → **525 passed, 4 deselected**, exit 0; `make lint-api` exit 0; `make config` shows `restart: unless-stopped` and both new settings. quickstart §6/§7 were rewritten to be executable (real routes, `TOKEN`/`WORKSPACE` setup, self-generated fixtures, `settings.json`, `PDF_PARSE_TIMEOUT_SECONDS=1` for the timeout case) — DB62's §6/§7 half. The checker must still run Section 6 live and must see the timed-out parse reclaim its CPU and memory; only a live run shows that, and a daemon child of a SIGKILLed API is a residual (see the iteration record).) Earlier: checker-fail (V138/V139, 2026-09-26: the single-file quickstart Section 6 path holds live. Mismatch, oversized, page-limit and timeout all fail with specific codes, and the next normal upload completes. The break: a timed-out parse's Docling thread keeps running (about 5 cores and 2 GiB, for minutes). 14 timed-out slow PDFs plus one normal upload caused an OOM kill of the API (exit 137, restart policy `no`), and it stayed down until a manual restart, which violates SC-009's "without requiring an app restart". See DB60.) Earlier: maker-ready (iteration 87, maker's own view, **not** a verdict: every US8 task is done — T061/T063/T064 in iterations 83-84 (magic bytes, `max_pdf_pages`, size cap) and T062/T065 in iteration 87 (a slow parse times out to a sanitized non-retryable `pdf_parse_timeout`, the version ends `failed`, and the next document ingests to `completed` on the same dispatcher and loop). Literal `make test-api` 480 passed, 4 deselected, exit 0; `make lint-api` exit 0. A checker must run quickstart.md Section 6 live against a real stack — that is what this criterion asks for, and it has never been run.) |
| D12 | New adversarial prompt-injection fixtures (T066) produce the same verifier/abstention outcome as their clean-text counterparts | Run the new test file; confirm assertions pass against primary test output, not maker's summary | checker-pass (V133/V134, 2026-09-26, medium confidence: 7 fixture tests and 15 verifier tests pass in the full run; the V127 attack now abstains on both fixtures. Break probes that differ between fixtures all require verbatim-quoting injected text, the structural limit pinned in the test file; DB54 limit accepted by human on 2026-09-26, wording unchanged. SC-006 will not be re-run, by human decision on 2026-09-26 (sign-off log).) Earlier: maker-ready (iteration 78, 2026-09-26: DB50 fixed with the human's option (a) — explicit values must appear in the *verified quote spans*, not the whole passage, so injected text sharing a passage with a real quote can no longer ground a fabricated date or entity. `make test-api` → **442 passed, 4 deselected**, exit 0; `make lint-api` → exit 0; a mutation check with the old passage-wide code restored fails **2 of the 3 new tests**, the integration one on `injection-adversarial.md` **only** (the clean fixture already abstained) — that asymmetry is exactly what this criterion measures. Maker belief only, and one caveat the checker must weigh: **SC-006 was not re-run**, because it needs a destructive corpus reset plus full reingestion.) Earlier: checker-fail (V126/V127, 2026-09-26: the file's 6 tests pass. The break attempt found that `_verify_explicit_values` matches `explicit_dates`/`explicit_entities` against the whole cited passage. A fabricated "shipped on 2026-08-01" claim that cites the genuine quote verifies `answered` on the adversarial fixture and `abstained` on the clean one, so the outcomes differ. See DB50 (high), which needs a human decision on verifier semantics.) Earlier: maker-ready (iteration 71, 2026-09-26: `api/tests/fixtures/injection-clean.md` + `injection-adversarial.md` (same real content, plus instruction-shaped lines in the adversarial one) and `api/tests/integration/test_prompt_injection_fixtures.py` — 6 tests, all passing. They assert the verifier's outcome is identical for both fixtures, that "cite no sources"/"skip the citation check" instructions are not obeyed (same abstention codes), that fixture text never reaches `system_instruction`, and — deliberately recorded rather than hidden — that a quote from a sentence the document really contains still verifies, because the verifier's contract is evidence-grounding, not truth. Maker belief only; the criterion is the checker running the file) |
| D13 | `.github/workflows/ci.yml` runs backend lint (ruff, pinned in `api/pyproject.toml`'s `dev` extra), a typecheck, `make test-api`, `make test-web`, and a fresh-DB migration check — every named check maps to a real job, and nothing is faked with `continue-on-error` | Inspect the workflow file and confirm the mapping (`lint` → ruff over `api/src api/tests`; `typecheck` → the `web-tests` job's `tsc -b` production build; `api-tests` → `make test-api`; `web-tests` → `make test-web`; `migration-check` → `alembic upgrade head` on a fresh `pgvector/pgvector:pg16`), then, if a CI run is available, its actual job results | checker-pass (V128, 2026-09-26: the workflow was inspected against the amended wording. Every named check maps to a real job and nothing uses `continue-on-error`. Local equivalents: ruff 0.13.2 from the repo root rc 0; fresh DB `upgrade head`, then `downgrade -1`, then `upgrade head`, rc 0. Medium confidence: `.github/` is untracked and has never run on a runner, and the `api-tests` job inherits DB49's flake.) Earlier: maker-ready (iteration 76, 2026-09-26: the human amended this criterion's wording rather than adding a tool, choosing option (d) from DB47. The old wording's "typecheck" was read by the maker as requiring an *API* static type check; the criterion never said that, and the workflow does run a real typecheck — `tsc -b` in the `web-tests` job, which `make test-web` alone does not perform. The API has no type checker **by decision**, tracked as a separate future increment in DB47, so this is a recorded scope decision and not a hidden gap. Maker belief only — the workflow has still never run on a runner, and D13's own check treats inspection as valid when no run exists. Earlier: pending (iteration 73, 2026-09-26: the workflow now exists with four jobs — `lint` (ruff over `api/src api/tests`), `api-tests` (`make test-api`), `web-tests` (`make test-web` + the `tsc -b` production build), `migration-check` (fresh `pgvector/pgvector:pg16` service container, `alembic upgrade head`, `current` must contain `(head)`, then a downgrade/re-upgrade). **Deliberately not `maker-ready`**: the criterion's "typecheck" half does not exist for the API (mypy reports ~100 errors unconfigured) and there is no web linter, so two of its words are unmet — that is debt DB47's decision, not something to fake with `continue-on-error`. Everything the workflow *does* run is verified by inspection; no runner has executed it yet. **Iteration 75, DB47 option (a)**: the lint half is now fully covered and cannot drift — the pin lives in `api/pyproject.toml`'s `dev` extra, the `test` image installs it, a documented `make lint-api` target runs it (`All checks passed!`, exit 0), and the CI `lint` job extracts that same pin from `pyproject.toml` instead of repeating it. The `typecheck` half is unchanged: still no API type checker and no web linter, i.e. DB47's remaining options (b)/(c)/(d). Iteration 76: the human settled that by choosing option (d) — the wording changed, no tool was added — which is what moves this row to `maker-ready`.) |

Statuses: pending → maker-ready → checker-pass | checker-fail → human-signed.

## Budget
- Max iterations: 150
- Iterations run: 104 (Iteration 104: **DB72(a) + DB73** — `retry_corpus_rebuild` now takes the
  process-wide provider-switch lock, re-reads its `failed` precondition *under* that lock (so a
  losing concurrent retry answers 409 instead of hitting the single-active-rebuild unique index),
  and dispatches with `request.app.state.provider_bundle_factory()` resolved after the lock rather
  than with the request-time `Depends` value a confirmed switch has already superseded and closed.
  Two new tests in `api/tests/integration/test_corpus_rebuild_retry.py`; each fix has a named mutant
  that fails exactly one of them (`1 failed, 1 passed` in both directions), the re-check mutant
  failing with the real `uq_corpus_rebuilds_one_active_per_workspace` `IntegrityError`. Gates:
  `make test-api` **543 passed, 4 deselected** exit 0; `make lint-api` exit 0; focused four-file run
  **37 passed**. No done-criterion was targeted, so D1-D13 keep their recorded statuses. New debt
  **DB75** (low: an evaluation-recovery test asserts an in-flight task count and raced once; see its
  row). Awaiting `/speckit.loop.check`.)
  Earlier: Iteration 103: **DB72** — the three residuals the checker opened in V170/V171. (a) `workspace/router.py`'s `retry_corpus_rebuild` now takes `acquire_provider_switch_lock(session)` before inserting its `pending` rebuild, so a manual retry and a confirmed switch on another workspace serialise instead of both passing the process-wide guard. (b) two route-level tests pin the call sites (`test_switch_route_takes_the_process_wide_lock`, `test_retry_route_takes_the_process_wide_lock`), each a spy that records the session and then calls the real lock; the mutant that deletes both calls now fails 2 of 2. (c) `Makefile`'s `test-api`/`test-web`/`lint-api` are each one shell command ending in `down -v` and re-exiting with the run's status, so a red run no longer leaves the isolated project's three volumes behind — proven live with a deliberately failing test (exit 1, no volumes left). Gates: `make test-api` **541 passed, 4 deselected** exit 0; `make lint-api` exit 0; `make test-web` **18 files, 79 passed** exit 0; focused re-run on the restored tree **35 passed**. No done-criterion was targeted, so D1-D13 keep their statuses. Awaiting `/speckit.loop.check`.)
  Earlier: Iterations run: 102 (Iteration 102: **DB67 + DB68 + DB69 + DB70** — the four debt rows the checker opened after iterations 97-101. DB67: all three over-cap files are split along a responsibility seam and no behaviour changed — `ingestion/service.py` 520 → **389** (embedding cache → `ingestion/embedding_cache.py`; decision persistence → `ingestion/decision_records.py`; `IngestionError` → `ingestion/errors.py`, re-imported by the service), `documents/service.py` 515 → **374** (read model → `documents/queries.py`; errors → `documents/errors.py`), `web/src/api/client.ts` 558 → **452** (transport half → `web/src/api/transport.ts`, re-exported under the old import path). DB68: the provider switch takes a constant-key `pg_advisory_xact_lock` before the rebuild guard, with `test_provider_switch_lock.py` killing the no-op mutant. DB69: the DB51 assertion now warms the pool and requires the api's pre-restore pooled backends to be gone afterwards (the restart mutant fails on it), and `make test-web` ends with `down -v`. DB70: `restore.sh` waits for the api's healthcheck before printing `Restore complete.`, and `docs/troubleshooting.md` names the parse-slot-wait cause of `pdf_parse_timeout` (two stale log-volume claims and a stale manual-restart instruction in the same file were corrected too). Gates: `make test-api` **539 passed, 4 deselected** exit 0; `make lint-api` exit 0; `make test-web` **18 files, 79 passed** exit 0; web production build exit 0; `make test-backup` **PASS**. New debt **DB71**: the DB51 behavioural probe could not be reproduced in this environment — see its row. No done-criterion was targeted, so D1-D13 keep their statuses. Awaiting `/speckit.loop.check`.)
  Earlier: Iteration 101: **DB53** — all six hand-written test files over the 500-line cap are split, by moving scaffolding to `api/tests/support/` and (for three of them) splitting the tests along a real seam: `test_ingestion_service.py`, `test_decisions_api.py`, `test_schema.py` + `test_schema_answering.py`, `test_hybrid_retrieval.py` + `test_hybrid_retrieval_decisions.py`, `test_gemini_provider.py` + `test_gemini_generation.py`, `test_evaluation_runs.py` + `test_evaluation_runs_api.py`; no test body rewritten. Earlier: Iteration 100: **DB63** — the parse-slot wait is bounded (`max(600s, 20 × timeout)`, injectable for the test, raising the documented `pdf_parse_timeout`), and the parse child runs a watchdog that exits when its parent dies; (c) per-PDF spawn cost and (d) a kill skipping Docling's cleanup stay accepted. Earlier: Iteration 99: **DB56 + DB61** — secret scrubbing now covers the percent-encoded, base64 and URL-userinfo forms of every configured secret; `/workspace/logs` became the `api_logs` volume; `uvicorn.error` dropped from the file handler's target list (it propagates to `uvicorn`, which caused every startup line and traceback to be written twice); ingestion failures log one line with ids and exception type only; `build_bundle` reports an unreachable database instead of 500-ing. Earlier: Iteration 98: **DB57 + DB65** (user-directed, keep the route) — the rebuild guard is now process-wide (`active_rebuild_workspace_ids`) and runs *before* the switch is persisted, the 409 preview lists every workspace's document count, and a local→remote switch clears every workspace's disclosure acknowledgement. Earlier: Iteration 97: **DB51 + DB52 + DB64 + DB66** — `restore.sh` restarts `api` after the restore and clears the uploads directory before extraction, both scripts read `POSTGRES_USER`/`POSTGRES_DB` from `.env`, the undeclared `web_node_modules` volume is gone from four docs, and §6's `retryable` claim matches the real response shape. Gates for the batch: literal `make test-api` → **538 passed, 4 deselected**, exit 0; literal `make test-web` → **18 files, 79 passed**, exit 0; `make lint-api` → `All checks passed!`; web production build exit 0; literal `make test-backup` → PASS (which also found that the script reused a 25-hour-old cached image — it now builds first). Real image IDs unchanged (`86d9b6719658`/`6773f0c063e7`). Two defects the maker introduced and fixed inside the batch are recorded in iterations.md: a class-body annotation shadowed by a method named `list`, and an ingestion failure log that read an expired ORM attribute after a savepoint rollback. Earlier: Iteration 96: **T072 executed** — quickstart.md all 8 sections live against an isolated clean checkout; `grep -c '^- \[ \]' tasks.md` = 0. Earlier: Iteration 95: **T051 fixed** — V146's mixed-configuration break. The disclosure now reports both providers plus per-provider remote flags and names the correct destination for each half of document text; new mixed-config test; `make test-web` 78 passed, `make test-api` 529 passed, `make lint-api` clean, web build clean. Earlier: Iteration 94: **DB62 fixed, then D1's US6/Polish half and D9's code half in one pass** — 7 tasks: T051 (`ProviderDisclosureGate` gating the source library, failing closed), T052 (`ProviderSettings` + the pending-rebuild `alertdialog`, confirming by resubmitting with `confirm_rebuild: true`), T053 (`docs/providers.md`), T067 (one table of the ten provider codes → an action, used by the answering, ingestion and switch paths), T068 (`CHANGELOG.md` + a test that enforces SemVer, version equality, and the FR-025 rebuild-impact line), T069 (`docs/uninstall.md` + `docs/troubleshooting.md`, plus the install/README stale-row repairs) and T071 (`.github/workflows/release.yml`: verify → gitleaks → push pinned `target: base`/`runtime` images, never the `test` stage, never `latest`). DB62's last defects are gone, including §7's unset-`$GEMINI_API_KEY` grep (which was `grep -F ""` — a leak check that always reported a leak). **D1 now has exactly one unchecked task: T072.** **D9 stays `pending`** by construction: its remaining work is the live §2 run `make setup` has never had, which the human deferred to T072. Literal `make test-web` → **18 files, 77 passed**; literal `make test-api` → **529 passed, 4 deselected**, exit 0 (after one red run whose only failure was the maker's own new test — fixed); `make lint-api` → `All checks passed!`; both workflows parse; real image IDs unchanged. Nothing here is checker-verified since V135. Earlier: Iteration 93: **DB60, D11's blocker** — the PDF parse now runs in a child process the timeout can kill (`ingestion/parse_runner.py`: `spawn` context, one `Pipe`, `kill()` + reap), bounded by a new `pdf_parse_timeout_seconds` (default 120; no longer `MODEL_TIMEOUT_SECONDS`) and a process-wide parse slot pool sized by `pdf_parse_concurrency` (default 1), with `restart: unless-stopped` on `api` as the backstop. New `test_parse_runner.py` parses a real PDF in a child and proves a 10 ms budget kills it and frees the slot; the timeout integration test now asserts no `docling-parse` child survives, which is V139's exact break. Literal `make test-api` → **525 passed, 4 deselected**, exit 0; `make lint-api` exit 0; rendered compose shows the restart policy and both settings. Also fixed DB62's §6/§7 half so the checker's live run is executable. **D11 → `maker-ready`**; D1 stays `pending` (8 tasks).
  Earlier: Iteration 92: **T044** — the web first-run "create password" screen, US5's last task. New `web/src/pages/FirstRunSetup.tsx` (two steps: password + confirmation, then the recovery code with an explicit "I saved my recovery code", because `POST /setup/password` returns that code exactly once) and `web/src/app/SetupContext.tsx` (`getSetupStatus`/`createPassword`, with a failed probe falling through to sign-in so an install that already has a user is never locked out). `App.tsx` now waits for the status answer before choosing a screen. 5 new tests + 2 adapted `App.test.tsx` cases; three failures were found by the gates and two were mine — the most important being a **real bug in the gate**: clearing `needs_password_setup` after the POST re-evaluated the gate and unmounted the recovery-code step, destroying the code in production; fixed with the reason recorded at the call site. Also: `App` owns its `BrowserRouter`, so tests must not wrap it in another router (React Router throws and the error boundary hides the cause). `make test-web` → **15 files, 64 passed** (incl. `tsc -b`); `make test-api` → **510 passed, 4 deselected** (run because an API file changed, comment-only). D1 stays `pending` (8 tasks); D9 stays `pending` (live run only).
  Earlier: Iteration 91: **T042 + T043 + T039** (US5 backend done) — `auth/bootstrap.py`'s `BootstrapService.ensure_user` is now `SetupService.status()`/`create_password()` with `PasswordAlreadySetUp` (409), `main.py` no longer creates a user at startup (so a fresh install has none and the first-run flow is the only way to make one), and the new `setup_router` serves `GET /api/v1/setup/status` + `POST /api/v1/setup/password` **without** a JWT, returning the recovery code once. `AUTH_BOOTSTRAP_*` is gone from `Settings`, `compose.yaml`, `.env.example` and the log-scrubbing secret set, with 19 now-dead references removed from six test files. `docs/install.md` and `quickstart.md` §2 were rewritten to the executable flow (D9's check runs the latter). 7 new integration tests + 3 T039 cases; a mutant deleting the 409 check fails exactly the 2 tests that assert it; literal `make test-api` → **510 passed, 4 deselected**, exit 0; `make lint-api` exit 0 after removing one import left behind by the deleted bootstrap call. New debt **DB59** (`/auth/signup` is open too, so `needs_password_setup` is a hint, not an authorization boundary). D1 stays `pending` (11 tasks); D9 stays `pending` (T044 + no live run).
  Earlier: Iteration 90: **T041 + T040** (US5 first-run secrets) — `make setup` (new `scripts/setup.sh` + `make setup` target) generates `AUTH_JWT_SECRET`, `POSTGRES_PASSWORD` and the `DATABASE_URL` that carries it into the host `.env`, then starts `db` and rotates the role password over stdin; every decision lives in the new `decision_assistant.setup.bootstrap` module (hex secrets, per-key keep/rotate, an `env`/`status` CLI reading `.env` on stdin), which is what makes T040's 14 tests possible. The human chose this split over T041's literal "`.env` the app manages", which is infeasible here — **DB58**, resolved. `config.PLACEHOLDER_DB_CREDENTIALS` is now the single source of truth for the DB8/DB26 placeholder check; `docs/install.md`'s first-run section leads with `make setup`. Focused run 1 failed on a **real defect in my implementation** (`EnvUpdate.skipped` was always empty, so the script could not report that it had kept existing secrets) — fixed and re-run green (22 passed); mutation (deterministic generator) fails exactly the 2 randomness-dependent tests; literal `make test-api` → **501 passed, 4 deselected**, exit 0; `make lint-api` exit 0. `scripts/setup.sh` itself is untested and has never been run. D1 stays `pending` (12 tasks left); D9 stays `pending`.
  Earlier: Iteration 89: **T050 + T047** (US6 provider switch) — the provider choice is now persisted (new single-row `app_settings` table, revision `0017_app_settings`, with `workspace/provider_config.py` owning the model and its four helpers) and applied over the environment defaults in `lifespan` before anything resolves a provider or a corpus profile; `POST /api/v1/workspaces/{id}/provider` refuses a profile-affecting change with a 409 preview and no side effects until `confirm_rebuild: true`, then persists, applies in process, creates the `CorpusRebuild`, swaps `app.state.provider_bundle_factory` and answers 202. Two error classes were added beyond the plan (`provider_switch_not_configured`, `corpus_rebuild_in_progress`) so a switch to an uncallable provider or a competing rebuild fails clearly instead of being persisted. 7 new tests; focused 29 passed; mutant `profile_changed = False` fails exactly the 3 gate-dependent tests; migration `0017` applies from a fresh DB, downgrades to `0016` and re-upgrades to `(head)`; literal `make test-api` → **487 passed, 4 deselected**, exit 0; `make lint-api` exit 0 first try. New debt **DB57** (the store is global, the route and its rebuild are per workspace). D1 stays `pending` (14 tasks left); D9 stays `pending` (US5 untouched).
  Earlier: Iteration 88: **T059** (US7 web download) — `downloadDiagnosticsBundle()` + `parseAttachmentFilename()` in `client.ts` and a `DiagnosticsDownload` component on the settings page (busy state, `aria-live` status, specific error alert, object-URL save with a deferred revoke); 6 new tests. `make test-web` → **14 files, 59 passed**, exit 0, which also runs `tsc -b`. Two jsdom traps found by the gate and fixed in the test harness (no `Blob.text()`; `Response(new Blob(...))` is stringified). **D10 → `maker-ready`** (checker must run quickstart Section 7 live and grep for encoded secret forms too, per DB56); D1 stays `pending` (16 tasks left).
  Earlier: Iteration 87: **T062 + T065** (US8) — a real-dispatch integration test proving a slow PDF parse times out to a sanitized non-retryable `pdf_parse_timeout` **and** that the next document still ingests to `completed` on the same loop; T065 confirmed the existing `asyncio.wait_for(to_thread(...))` wrap, no product code changed; new shared helpers in `tests/support/ingestion_fixtures.py`. Focused 1 passed; mutant (`timeout=3600`) fails the test; literal `make test-api` → **480 passed, 4 deselected**, exit 0, zero failures; `make lint-api` exit 0 first try. **D11 → `maker-ready`** (checker must run quickstart Section 6 live); D1 stays `pending` (17 tasks left).
  Earlier: Iteration 86: **T058 + T060** (US7 backend) — authenticated `GET /api/v1/diagnostics/bundle` returning an in-memory zip with download headers (new `diagnostics/router.py`, 2 tests: 401 without credentials, 200 with a readable scrubbed archive carrying the real DB revision), plus T060's grep evidence (zero telemetry/error-reporting clients in either source tree or either dependency manifest). Focused 18 passed; auth mutant fails exactly the 401 test; literal `make test-api` → **479 passed, 4 deselected**, exit 0, zero failures; `make lint-api` failed once on an unused import in the new test file, fixed → exit 0, focused file re-run 2 passed. T058/T060 → `maker-ready`; D1 stays `pending` (19 tasks left). D10 still needs T059 (the web download action) plus the live quickstart Section 7 run.
  Earlier: Iteration 85: **T046 + T049** (US6 disclosure gate) — `DisclosureNotAcknowledged` (409) enforced in `submit_uploads` (service, not router, so every caller is covered), with `document_fixtures.py`/vertical-slice workspaces pre-acknowledged and both HTTP scripts (`ingest_corpus.py`, `smoke.py`) acknowledging first so the documented corpus-reset flow keeps working; 2 new tests. Focused 27 passed (first attempt caught a test that overrode the very dependency it asserted on); mutant removes the gate → exactly the gate test fails; literal `make test-api` → **477 passed, 4 deselected**, exit 0, zero failures; `make lint-api` exit 0; real images unchanged. T046/T049 → `maker-ready`; D1 stays `pending` (21 tasks left). D9 still needs T047/T050-T053 and all of US5 (auth escalation).
  Earlier: Iteration 84: **DB55** (checker V136) — the UTF-8 text probe now uses an incremental decoder and knows whether the file ended inside the probe, so a multi-byte character straddling byte 8192 no longer rejects a valid file, while a truncated tail in a short file still does. The checker's own V136 probe became a repo test; reverting to `final=True` fails exactly that test. Focused 24 passed; literal `make test-api` → **475 passed, 4 deselected**, exit 0; `make lint-api` exit 0; real images unchanged. DB56 remains open (low). D1 stays `pending` (23 tasks left).
  Earlier: Iteration 83: **T061 + T063 + T064** (US8 upload validation) — `ingestion/validation.py` with magic-byte checks for PDF/docx, a UTF-8/NUL probe for text, and `max_pdf_pages` (new `Settings` field, default 200) enforced via `pypdfium2`, called from `_parse_for_ingestion` ahead of the frozen `parse_document`; 8 tests. Focused 28 passed; mutants attributed per check (magic off → 4 fail, page limit off → exactly 1); the first full gate was **red** (2 failed, 471 passed — two `test_pdf_parser.py` `SimpleNamespace` Settings stubs missing `max_pdf_pages`), fixed, then literal `make test-api` → **473 passed, 4 deselected**, exit 0 with `make lint-api` exit 0 and real images unchanged. T061/T063/T064 → `maker-ready`; D1 stays `pending` (23 tasks left). D11 still needs T062/T065.
  Earlier: Iteration 82: **T055 + T057** (US7 diagnostics bundle) — `diagnostics/bundle.py` with three independent guards on the config dump (allowlist, credential-name refusal, scalar-only values), `assemble_bundle`/`build_bundle` split, and `migrations.current_db_revision` as a public wrapper instead of shelling out to `alembic`; 7 tests. Focused 16 passed; mutants attributed per test (name guard → the adversarial test only; no log files → the rotated-log test only); literal `make test-api` → **465 passed, 4 deselected**, exit 0; `make lint-api` exit 0; real images still `86d9b6719658`/`6773f0c063e7`. T055/T057 → `maker-ready`; D1 stays `pending` (26 tasks left). D10 still needs T058/T059/T060.
  Earlier: Iteration 81: **T048** (US6 disclosure half) — `providers/disclosure.py` (`active_provider`, `sends_document_text_remotely` with `ollama` the only offline provider, unknown names failing toward disclosure), `ProviderDisclosureResponse`, `WorkspaceService.acknowledge_provider_disclosure` (idempotent, first timestamp kept) and the owner-scoped `GET`/`POST .../ack` routes in `workspace/router.py`; 7 new tests. Focused 29 passed; a three-mutant injection (remote flag forced False, timestamps re-stamped, owner filter dropped) failed 5 of 7; literal `make test-api` → **458 passed, 4 deselected**, exit 0; `make lint-api` exit 0 after removing one unused import, with the focused file re-run on the final tree (7 passed). T048 → `maker-ready`; D1 stays `pending` (28 tasks left). D9 is not close: T049/T046 + T047/T050-T053 + all of US5 (auth escalation) remain.
  Earlier: Iteration 80: **T054 + T056** (US7 logging) — new `diagnostics/logging.py`: `secret_values`, `scrub_secrets`, `SecretScrubbingFilter`, `SecretScrubbingFormatter`, `configure_logging`, plus `log_directory`/`log_level`/`log_max_bytes`/`log_backup_count` on `Settings` and a `create_app` call. Nine tests; two mutation checks behaved exactly as intended (`scrub_secrets` no-op → 5 failed; `formatException` deleted → only the traceback test failed). `make lint-api` exit 0 (after removing an unused import); literal `make test-api` → **451 passed, 4 deselected**, exit 0 on the final tree; real image IDs unchanged. T054/T056 → `maker-ready`; D1 stays `pending` (29 tasks left). D10 is the target this advances but is not close: T055, T057, T058, T059 remain.
  Earlier: Iteration 79: **T038** — `docs/backup-restore.md` written (110 lines, new file) and linked from `docs/install.md`, with T038 flipped to `[X]`: both commands plus their `scripts/*.sh` equivalents, the archive layout (`database.sql` + `uploads.tar`), FR-009's warning against `down -v` (and `docker volume rm`/`system prune --volumes`), the automatic pre-migration backup with its
  `PRE_MIGRATION_BACKUP_RETENTION`, and DB51/DB52's restore residuals as explicit operator steps
  (restart `api`; additive upload extraction; `POSTGRES_USER`/`POSTGRES_DB` come from the
  environment, not `.env`). Docs-only: no API/web code touched, so no `make test-api`/
  `make test-web` gate applied and no image rebuild needed; `make -n backup`,
  `make -n restore -- <file>` and bare `make restore`'s usage guard verified against the Makefile.
  T038 → `maker-ready`; D1 stays `pending` (31 tasks remain, and US5/T042 is an authentication
  change that needs escalation first).
  Earlier: Iteration 78: **DB50, option (a)** per the human's decision — `explicit_dates`/
  `explicit_entities` are now grounded in the verified citation quote spans rather than the cited
  passage's whole content, so injected text can no longer supply the "evidence" for a fabricated value.
  New tests at the verifier's layer (value in the passage but outside the quote → abstain; value inside
  the quote → answer) and a both-fixtures test in `test_prompt_injection_fixtures.py` that, with the old
  behaviour restored, fails on `injection-adversarial.md` alone. Literal `make test-api` → **442 passed,
  4 deselected**, exit 0; `make lint-api` → exit 0; focused set → 44 passed. Also recorded: the human's
  `docker system prune` cleared the build cache (1.2 GB → 25.7 GB free), so the first build after the
  code change was a full ~10 min rebuild while later src-only rebuilds were back to ~14 s — iteration
  77's disk-pressure warning is moot. **SC-006 was not re-run** (destructive reset → escalation). D12 →
  `maker-ready`.
  Earlier: Iteration 77: **DB49** — D2's blocker. `_SOURCE_TEXT_2` was a superset of
  `_SOURCE_TEXT`, and a rebuild truncates `embedding_cache` first, so a later document with
  byte-identical chunk text is served entirely from the cache and the staged provider outage never
  fires; DB48's new `created_at DESC, id DESC` tiebreaker made the processing order a coin flip, so
  the abort test failed about half the time. The fixture is now a *disjoint* document — chosen over
  fixed uuids because disjointness makes the test order-independent instead of pinning one order.
  The fixture half moved to `api/tests/support/corpus_rebuild_fixtures.py` so the test file (486
  lines) stayed under AGENTS.md's 500-line cap; **DB53 opened** for six other test files already
  over it. Literal `make test-api` → **439 passed, 4 deselected**, exit 0; `make lint-api` → exit 0;
  abort test 14/14 in isolation against 2/2 failures with the old fixture restored. D2 → `maker-ready`.
  Earlier: Iteration 76: D13's wording **amended at the human's direction** — option
  (d) from DB47 — after the maker's reading of "typecheck" as requiring an API static type check
  turned out to be stricter than the criterion. The criterion and its check column in this file,
  T070 in tasks.md, and the CI workflow's header now name the checks that exist and the one that
  does not (an API typecheck, tracked as its own future increment in DB47). D13 moved `pending` →
  `maker-ready`. No code changed; the workflow YAML was re-parsed and the job→check mapping
  confirmed. Earlier: Iteration 75: **DB47 option (a)** per the human's decision — `ruff==0.13.2`
  moved into `api/pyproject.toml`'s `dev` extra, so the `test` image installs it and a new
  `make lint-api` target (documented in AGENTS.md) runs the same pinned, configured linter a
  developer gets; the CI `lint` job now extracts that pin from `pyproject.toml` instead of
  repeating it. `make lint-api` → `All checks passed!`, exit 0; literal `make test-api` →
  **439 passed**, exit 0. Also closed **DB46** (stray pre-migration archive deleted at the human's
  direction). D13 stays `pending`: option (a) settled the linter, but the criterion's "typecheck"
  still has no API counterpart, which is DB47's remaining options (b)/(c)/(d).
  Earlier: Iteration 74: **DB48** — the human's second finding. A successful rebuild re-ordered the
  document list because `created_at` is a `server_default` of `func.now()`, i.e. the *transaction*
  timestamp, and the rebuild re-creates every `Document` (same id) in one transaction: every
  re-created row held an identical timestamp, so `ORDER BY created_at DESC` had nothing left to
  sort by. Fixed by carrying `created_at` through `DocumentSnapshot` onto the re-created row,
  ordering the (previously unordered) snapshot query to match `list_documents`, and adding
  `Document.id DESC` as the tiebreaker. New `test_corpus_rebuild_ordering.py`: 2 tests, both
  confirmed to fail against a reverted copy of the source.
  Earlier: Iteration 73: T070 — `.github/workflows/ci.yml` with jobs `lint` (ruff,
  pinned `0.13.2`, installed by the job), `api-tests` (`make test-api`), `web-tests`
  (`make test-web` + `tsc -b` production build), `migration-check` (fresh
  `pgvector/pgvector:pg16` service container, `alembic upgrade head`, `current` contains
  `(head)`, then downgrade/re-upgrade). YAML validated; the workflow header records the two
  checks it deliberately does *not* fake. **DB47 opened**: no Python type checker (mypy: 103
  errors unconfigured) and no web linter, both needing a dependency decision — so D13 stays
  `pending` until that is settled. Earlier: Iteration 72: lint enablement for
  T070's gate — fixed all 32 ruff findings (unused imports/variables, and the fixture import
  shadowed in `test_documents_detail.py`/`test_documents_upload.py`); `ruff check src tests` is
  now clean. Evidence gathered while deciding: 4 findings in `src`, 28 in `tests`, mypy at 103
  errors. `make test-api` 431 passed, exit 0 after the cleanup.
  Earlier: Iteration 71: T066 — adversarial
  prompt-injection fixtures + `test_prompt_injection_fixtures.py`, 6 tests, all passing.
  Earlier: Iteration 70: D8's host-side half — new `scripts/test_backup_restore.sh` +
  `make test-backup` run the documented `scripts/backup.sh`/`scripts/restore.sh` flow against an
  isolated project (`COMPOSE_PROJECT_NAME`, `BACKUP_DIR` and `API_PORT` all redirected so a live
  dev stack is untouched), seed → backup → wipe → restore, and assert row counts and the upload
  file match. Result: `PASS`. `AGENTS.md`'s command block was repaired in the same iteration — it
  documented the bare `docker compose run --rm web npm run build` that DB46 records reaching the
  live stack.
  Earlier: Iteration 69: DB45 + T032 — `web/src/components/CorpusRebuildBanner.tsx`
  (+css, +6 tests) polls `GET .../corpus-rebuild` through new client calls, shows `n/m documents`,
  reports a failed rebuild with its error code and a **Retry rebuild** button that resumes polling,
  and hides itself when no rebuild has run (404); rendered from `Workspace.tsx`. `docs/upgrade.md`'s
  banner sentence is now true and more precise. `make test-web` 51 passed, isolated production web
  build clean. **DB46 opened**: the maker ran the documented `docker compose run --rm web npm run
  build` without `-p`, which started the real `db`/`api` (still up) and let the app migrate the
  real dev DB to `0013` with its pre-migration backup in `./backups`; images unchanged, no rebuild
  dispatched. Real project was not touched further — human decision needed on containers/archive.)
  Earlier: Iteration 68: DB44 — chose option (a): one helper, `_failed_fields`, now defines a
  failed row's fields for all three failure paths (abort, systemic failure, interrupted sweep), so
  none of them can keep reporting rolled-back progress. The abort test asserts the intermediate
  `running 1/2` instead of assuming it, plus new coverage for the systemic path and the sweep.
  Focused run → 4 passed. Earlier: Iteration 67: two defects from the batch. (1) An aborted rebuild no longer
  reports progress it discarded — `dispatch.py`'s `RebuildAborted` branch commits
  `documents_completed: 0`, so a failed row cannot read `failed 4/7` after DB43 rolled those four
  documents back (human finding). (2) The batch's own full-suite gate caught T027's first-status
  assertion failing only in-suite (`statuses[0]` was `not_started`, the 404-before-first-row
  window); the window is now filtered out of the first-status claim but kept in the failure
  message. The abort test now seeds two documents with different content so one completes before
  the staged failure, which is what makes the `completed == 0` assertion discriminate.)
  Earlier: Iteration 66: T034 — new `api/tests/integration/test_backup_restore.py` runs
  a real round trip in-container: live `pg_dump` via `create_pre_migration_backup`, wipe of the
  seeded rows and upload files, restore through `psql -v ON_ERROR_STOP=1` (the invocation
  `scripts/restore.sh` uses), and exact row-count/file-list comparison. The host-side script path
  remains quickstart Section 5's job. `pytest .../test_backup_restore.py -q` → 1 passed.)
  Earlier: Iteration 65: T033 — wrote `docs/upgrade.md` (startup order, rebuild
  triggers, replaced vs preserved tables, re-link rules, progress/retry endpoints, DB43 abort,
  `down -v` warning), every command and env var verified against `Makefile`/`compose.yaml`/
  `.env.example`, plus an upgrade pointer from `docs/install.md`. Docs only, no test gate.)
  Earlier: Iteration 64: T027 — new
  `api/tests/integration/test_upgrade_rebuild_flow.py` drives the real `lifespan` scan on a
  changed chunking preset and polls `GET /api/v1/workspaces/{id}/corpus-rebuild` while asserting
  the decisions/conversations reads are unchanged at every poll (only `passage_id` /
  `document_version_id` / `stale` normalized out); a gated embedding provider makes `running`
  observable instead of racy, and completion is asserted by the re-link actually happening. Also
  fixed quickstart.md Section 4's namespace and missing auth header, per the human report.
  `pytest tests/integration/test_upgrade_rebuild_flow.py -q` → 1 passed.)
  Earlier: Iteration 63: fixed DB43 (checker V118) with the human's option A — a
  per-document re-ingestion failure now raises `RebuildAborted` inside the still-open corpus
  transaction, `dispatch._run` rolls that transaction back and only then records `failed` +
  the document's error code on the `CorpusRebuild` row (its own session, DB41), so the
  workspace keeps its pre-rebuild corpus, passages, and decision/evidence links and the retry
  re-runs against real data. New `api/tests/integration/test_corpus_rebuild_abort.py`. The added
  docstring and exception pushed `coordinator.py` to 515 lines, so the snapshot/re-link half
  moved to `workspace/rebuild/relink.py` (coordinator 306, relink 238). D7 moved
  `checker-fail` → `maker-ready` (not `checker-pass`). `make test-api` 428 passed, exit 0. See
  iterations.md Iteration 63, memory.md M-061.)
  Earlier: Iteration 62: closed the three checker findings against D7 — DB40 residual,
  DB41, DB42 — all three fix shapes specified by the human in the iteration request. DB40: new
  revision `0016_evidence_quote` stores the quote on `decision_evidence` (backfilled from the
  passage for rows that still have one) and the readers serve it; the coordinator re-links
  evidence by identical `content_hash`, then by locating the stored quote inside the rebuilt
  passages, then `NULL` + `citation_stale`. DB41: the `CorpusRebuild` row is committed before the
  work starts and progress is committed in its own session (`workspace/rebuild/dispatch.py`), so
  `GET .../corpus-rebuild` reports `running` mid-rebuild while the corpus swap still commits once
  at the end (V108's guarantee kept); new `mark_interrupted_rebuilds` sweeps crash-left rows to
  `failed` at startup, wired into `main.py`'s lifespan before the `corpus_reset_required` scan.
  DB42: documents without an active version are preserved by the truncate instead of deleted with
  their retry path. D7 moved `checker-fail` → `maker-ready` (T027/T032/T033 still open, so not
  `checker-pass`). `make test-api` 427 passed, exit 0; fresh-DB chain to `0016_evidence_quote
  (head)`; the 0016 backfill proven against a real pre-0016 row. See iterations.md Iteration 62,
  memory.md M-060.)
  Earlier: Iteration 61: implemented T028-T031 — `CorpusRebuildCoordinator`'s
  redispatch and re-link, lifespan wiring, and the retry/status endpoints. Fixed loop debt DB39
  (orphaned-decision migration failure) and DB40 (rebuilt decisions dropping from timelines/
  retrieval/answering — partially: fixed for the common case, residual gap when re-chunking
  reshapes a chunk past content-hash matching). D7 moved `pending` → `maker-ready`, not
  `checker-pass` — T027's actual integration test is still unwritten and none of this is
  independently checker-verified yet. `pytest -q -m "not live_provider"` 422 passed (twice, after
  fixing a test-only cross-loop connection-pool flake in the retry endpoint's background-task
  test). See iterations.md Iteration 61, memory.md M-059.)
  Earlier: Iteration 60: resolved DB37 and DB38 per explicit human decisions.
  DB37: `truncate_corpus_derived_tables` no longer deletes `retrieval_traces` (reclassified
  non-derived, no FK to corpus-derived rows, no schema change). DB38: new revision
  `0015_decisions_workspace_id` denormalizes `workspace_id` onto `decisions`, backfilled from
  the old chain; `decisions/service.py` scopes by it directly and outer-joins `Passage` for
  evidence so a nulled `passage_id` still surfaces; `schemas.py`/`web/src/api/types.ts`/
  `DecisionEditor.tsx`/`DecisionDetail.tsx` updated for nullable `document_version_id`/
  `passage_id`/`quote`; every test fixture constructing `Decision(...)` updated (7 files).
  `make test-api` 412 passed, `make test-web` build+45 passed. D7 stays `pending` — T027-T031
  remain. See iterations.md Iteration 60, memory.md M-057/M-058.)
  Earlier: Iteration 59: implemented T026 — new
  `workspace/rebuild/coordinator.py`'s `truncate_corpus_derived_tables` deletes a workspace's
  corpus-derived rows (`documents` cascades to `document_versions`/`passages`/`ingestion_jobs`;
  `embedding_cache`/`retrieval_traces` deleted directly), matching data-model.md's table list
  exactly; new `test_corpus_rebuild.py` proves this composes with iteration 58's DB34 fix —
  `decisions`/`decision_evidence` survive with a nulled FK, not deleted. Corrected
  data-model.md's stale "untouched" wording. T026 now `[X]`. `make test-api` 412 passed. This is
  only the truncate-scope slice of T028, not the coordinator/lifespan/endpoint/citation_stale
  work (T028-T031) — D7 stays `pending`. See iterations.md Iteration 59, memory.md M-056.)
  Earlier: Iteration 58: fixed DB34's schema blocker for D7 — Alembic revision
  `0014_decision_setnull_fk` makes `decisions.document_version_id`/`decision_evidence.passage_id`
  nullable with `ON DELETE SET NULL` (was NOT NULL + `ON DELETE CASCADE`), matched in
  `decisions/models.py`. Live-verified on a fresh DB: a decision survives its
  `document_version_id`'s deletion with the FK nulled, not cascaded away. `make test-api` 411
  passed. T026-T031 (`CorpusRebuildCoordinator` itself) remain unimplemented; D7 stays `pending`.
  See iterations.md Iteration 58, memory.md M-055.)
  Earlier: Iteration 57: **DB35 verified fixed** — the human committed the Dockerfile
  layer-order refactor as `281a525`; this iteration checked it rather than re-implementing it.
  Source-only edit then rebuild: base 6.17 s, test 7.15 s, dependency/model layer `CACHED` (was
  5–15 min). Parity diff found one drifted transitive dep, opened as **DB36** (`docling-core`
  2.98.1 → 2.99.0 — floating, and on the parser path the corpus profile only guards by the
  `docling` distribution version). `make test-api` 410 passed; D5 `alembic upgrade head` on a fresh
  isolated DB → `0013_eval_run_attempt_count (head)`. See iterations.md Iteration 57.)
  Earlier: Iteration 56: scoped **D7** and stopped — **blocked on DB34**, no code written.
  `decisions.document_version_id` and `decision_evidence.passage_id` are NOT NULL with
  `ondelete="CASCADE"`, so US3's truncate scope would delete the decisions D7 requires to survive;
  T026's planned unit test would pass while the data disappeared. Needs a human decision on the
  schema shape (recommended: nullable columns + `ON DELETE SET NULL`, revision 0014, plus a
  `data-model.md` correction). See iterations.md Iteration 56.)
  Earlier: Iteration 55: **DB32 resolved by human decision** — evaluation stays a
  development-only surface. `quickstart.md` §3, `README.md`, `docs/install.md` and `AGENTS.md`
  now say so; `EvaluationService._load_dataset` reports a missing benchmark as
  `evaluation_unavailable` (503) instead of `dataset_invalid`, with a new unit test for both
  codes. No task IDs moved; the spec text was left for the human. `make test-api` 410 passed. See
  iterations.md Iteration 55.)
  Earlier: Iteration 54: targeted **D6** (quickstart.md Section 3). Executed the section
  for real against an isolated production stack: SIGKILL the api 8 s after upload, restart, then
  `GET /documents/{id}` reached `completed` (100%) in 3 polls with no manual resubmission; log
  shows `startup recovery: requeued 1 ingestion job(s) (1 dispatched), marked 0 failed`; DB has a
  single `completed` job row with `attempt_count 1`. That log line did not exist before this
  iteration — `main.py` now emits startup-recovery counts through `uvicorn.error` (US7/T056 will
  install real app logging), because quickstart Section 3's own check greps the container log and
  the app configured no logging at all. Opened DB32: the evaluation half of Section 3 cannot run
  in the production image (dataset file is outside the build context). `make test-api` 408 passed
  (407 + the new log-assertion test). See iterations.md Iteration 54.)
  Earlier: Iteration 53: fixed DB31 (`low`, found by checker V96) — `retry()` now
  locks the document row with `with_for_update()` before reading the latest `IngestionJob`, so
  two simultaneous retries serialize and the loser gets 409 `retry_not_available` instead of
  dispatching a second job. Chose the lock over a partial unique index to avoid a schema
  migration. New `test_documents_retry_concurrency.py` (two real sessions) kills the no-lock
  mutant. `make test-api` 407 passed. See iterations.md Iteration 53.)
  Earlier: Iteration 52: fixed checker V97 (`fail`, high) — `Workspace.tsx`'s
  `handleRetry` read `sourceDocument` from a stale closure, so closing the detail view during
  an in-flight retry reopened it, and a different document opened meanwhile was overwritten.
  Replaced with an `openDocumentIdRef` kept in sync by `openSourceDocument`, checked after the
  retry await **and** after the refresh fetch resolves. Split test fixtures to
  `web/src/test/documentFixtures.ts` and added `Workspace.retryRefresh.test.tsx` (3 tests) to
  stay under the 500-line cap. Two in-container mutants both killed. `make test-web` 45 passed;
  web production build clean. See iterations.md Iteration 52.)
  Earlier: Iteration 51: fixed checker V94 (DB29, high) and V95 (DB30, high) against
  iteration 50's T024/T025 — `DocumentService.retry()` now requires the document's LATEST job
  (not merely the latest `failed` one) to be `failed`, closing a double-dispatch race;
  `Workspace.tsx` re-fetches the open detail view after a successful retry so it stops showing
  stale state. Split `test_documents_api.py` (538 lines) into
  `tests/support/document_fixtures.py` + `test_documents_upload.py` + `test_documents_detail.py`,
  all under 500 lines. Full suite `make test-api` 406 passed, `make test-web` 42 passed, `npm
  run build` clean. See iterations.md Iteration 51.)
  Earlier: Iteration 50: T024/T025 — added `status`/`stage`/`progress`/`error` to
  `DocumentDetail` (`GET /documents/{id}`), populated from the document's latest `IngestionJob`.
  Found T025's list-view retry state already existed from an earlier iteration; added the
  missing detail-view half to `SourceViewer.tsx`, extracting the shared retryability check into
  `IngestionStatus.tsx`'s `canRetryDocument`. Full suite `make test-api` 404 passed, `make
  test-web` 41 passed, literal `docker compose run --rm web npm run build` succeeded clean.
  See iterations.md Iteration 50.)
  Earlier: Iteration 49: fixed checker V90's DB28 — `recover_and_requeue` gained
  `finished_at_field` (stamps `finished_at`/`completed_at` on terminal `failed`, matching
  `_record_dispatch_failure`/`_fail_run`'s existing behavior); fixed both `main.py` call
  sites, not just `EvaluationRun` (ingestion had the identical latent gap). Added the lifespan
  integration test DB28 asked for, for both models, plus 2 unit tests. Full suite `402 passed,
  4 deselected, 0 failed`. See iterations.md Iteration 49.)
  Earlier: Iteration 48: T023 — per explicit human decision ("add a new migration"),
  added Alembic revision `0013_eval_run_attempt_count` (`evaluation_runs.attempt_count`),
  made `recover_and_requeue`'s error field configurable (`error_field`, default `"error"`
  unchanged) and passed `error_field="failure"` for `EvaluationRun` (its failure column is
  named `failure`, kept as-is rather than renamed). Wired an `EvaluationRun` sweep into
  `main.py`'s `lifespan` (`statuses=("running", "pending")`, same DB27-class fix applied from
  the start) redispatching via `EvaluationBackgroundRunner`. New tests reach a genuine
  `completed` terminal state via the real dispatch path (not a stub), matching T020's
  precedent. Full suite `398 passed, 4 deselected, 0 failed`. Migration applied clean
  (`alembic upgrade head && alembic current` -> `0013_eval_run_attempt_count (head)`). Hit and
  fixed a revision-id-too-long gotcha (`alembic_version.version_num` is `varchar(32)`). See
  iterations.md Iteration 48.)
  Earlier: Iteration 47: T022 — confirmed `submit_uploads`/`retry` already persist
  the `IngestionJob` row before `background_tasks.add_task` fires (no code change needed),
  added a regression test proving it (`test_documents_api.py`, job status read at dispatch
  time). T023 NOT implemented and escalated to the human: `recover_and_requeue` needs
  `EvaluationRun` to have an `attempt_count` column and an `error`-shaped field, neither of
  which exist (`failure` is JSONB but not named `error`) — this is a schema migration, which
  AGENTS.md requires asking about first. Full suite `395 passed, 4 deselected, 0 failed`. See
  iterations.md Iteration 47.)
  Earlier: Iteration 46: fixed checker V84/V85's two findings against iteration 45's
  T020/T021 claim — DB27 (`recover_and_requeue` now sweeps `statuses=("running", "pending")`
  for `IngestionJob`, not just `running`; redispatch `asyncio.create_task`s are now held in
  `application.state.startup_redispatch_tasks` so they can't be GC'd) and T020 (rewrote
  `test_ingestion_restart_recovery.py` to run the real redispatch path to genuine `completed`
  terminal state for both a `running`-left and a `pending`-left job, instead of asserting on a
  stub call). Full suite `394 passed, 4 deselected, 0 failed`, zero regressions; real project
  untouched. No D-id status changed directly (D6 still needs T022/T023 and the rest of
  quickstart.md Section 3); DB27 moved to maker-fixed, pending checker re-verification. See
  iterations.md Iteration 46.)
  Earlier: Iteration 45: wired `recover_and_requeue` into `main.py`'s `lifespan`
  startup (T021) and added `test_ingestion_restart_recovery.py` (T020); full non-live suite
  `393 passed, 4 deselected`. See iterations.md.)
  Earlier: Iteration 44: fixed DB19 dangling `docs/backup-restore.md` links per V80;
  completed T019 unit tests for `recover_and_requeue`, `3 passed`. See iterations.md.
  Earlier: Iteration 43: fixed every checker-fail debt from V73-V77 — DB15 (added
  the missing `build api` step to `AGENTS.md`'s documented single-file test command), DB19
  (rewrote `docs/install.md`'s First-run section again per all 4 V75 findings), DB8
  robustness (2 new mutant-kill lifespan-wiring tests; `validate_startup_config` now parses
  `DATABASE_URL` via `sqlalchemy.engine.make_url` and compares username/password instead of
  the whole string, closing V76(b)'s bypasses; 4 new adversarial/negative test cases), and
  DB26 (per explicit human decision "rotate the real password now": generated a real random
  password entirely inside a Python subprocess, never printed anywhere; rotated the real
  `db` container's role password via SQL piped over stdin to `psql`, not a shell arg;
  updated the real `.env`; live-verified the real stack boots clean —
  `docker compose up -d api --wait` both `Healthy`, `/health` → 200, no
  `ConfigurationError`). Live-verified: full `make test-api` `389 passed, 4 deselected, 0
  failed` (383 + 6 new, zero regressions); the corrected literal AGENTS.md command run
  against both touched test files, `20 passed`; real `decision-assistant-{api,web}:latest`
  image IDs confirmed unaffected. Deliberately booted the real (not isolated)
  `decision-assistant-{api,db}-1` containers this one time to prove DB26 against the actual
  deployment — disclosed, not incidental. See iterations.md Iteration 43.)
  Earlier: Iteration 42: resolved DB20 and DB8 per explicit human decisions on
  each. DB20: human chose to commit `specs/002-production-readiness/` — grepped the tree for
  secret-shaped literals first (none found), then `git add specs/002-production-readiness/`
  (all 13 files, `tasks.md` through `loop/*.md`); staged, deliberately NOT committed (user
  asked for `git add`, not a commit). DB8: human chose "startup guard now" over waiting for
  US5 or patching quickstart.md's check — implemented T045 (now `[X]`), wiring the
  already-existing `validate_startup_config()` into `main.py`'s `lifespan` as the first
  statement, before any DB access; raises `ConfigurationError` on a missing
  `AUTH_JWT_SECRET` or the placeholder `DATABASE_URL`. Live-verified via a direct probe
  against the real built image (not just a unit test): placeholder `DATABASE_URL` correctly
  rejected, real config correctly passes. Full suite rerun: `383 passed, 4 deselected, 0
  failed`, zero regressions (M-018/M-028's existing lifespan-test-secret pattern already
  covered this). Also cleared an environment-only Docker-VM disk-full blocker (same class as
  V34) with explicit user approval — removed 20 leftover throwaway checker/loop-iter images,
  freed ~28GB; real image tags/containers confirmed unaffected. See iterations.md
  Iteration 42.)
  Earlier: Iteration 41: closed out maker-fixable open debt per explicit user
  instruction ("for the remaining debts"), not a D-id target — DB17 (added
  `api/tests/unit/test_config_validation.py`, 4 tests for `validate_startup_config()`, which
  had none), DB15 (fixed `AGENTS.md`'s broken documented single-file test command), DB19
  (fixed `docs/install.md`'s "First run" section, which described the unbuilt US5 flow as
  already current), and DB16 (bookkeeping-only close — the underlying gap was already fixed
  and checker-verified in Iterations 37/38/40, `debt.md` just never reflected it). Live-verified:
  full `make test-api` 383 passed/4 deselected/0 failed (379+4 new, zero regressions); the
  literal new AGENTS.md command run against the new test file, 4 passed; real
  `decision-assistant-{api,web}:latest` images/containers confirmed unaffected. Left DB8 and
  DB20 open — both explicitly need a human decision, not a maker default. D1 unaffected (still
  51 tasks, T019-T072, unchecked; this iteration was debt-only, not D1 work). See
  iterations.md Iteration 41.)
  Earlier: Iteration 40: fixed checker V68 — V64's fix was only partial, the
  `lifespan` gate/order itself (`main.py:116-118`) had no test, so deleting the `if
  is_upgrade_pending(...)` gate or reordering backup after `upgrade_to_head()` would have
  stayed green. Added the 2 tests V68 itself specified to `test_app.py`: pending=False skips
  backup but still upgrades; backup failure blocks the upgrade and still runs cleanup. Full
  suite `379 passed, 4 deselected, 0 failed` in isolated project `da-iter40`, real project
  confirmed untouched. Targets D1. See iterations.md Iteration 40.)
  Earlier: Iteration 39: fixed debt DB24 — the DB18/DB21 Makefile/compose.yaml
  fixes that D3's earlier `checker-pass` (V54-V57) rested on were never merged into
  `improvement`, only existing on orphaned worktree/branch `loop-iter-31`. Hand-ported both
  commits' diffs directly onto `improvement`'s working tree (git merge wasn't viable without
  first committing iterations 33-38's own uncommitted changes, out of scope here): `compose.yaml`
  pins `web`'s build target, `Makefile`'s `test-api`/`test-web` isolate to `-p
  decision-assistant-test`. Live-verified with the literal bare `make test-api`/`make test-web`
  commands (not a workaround): both exit 0 (377 passed; 38 passed/11 files), real
  `decision-assistant-{api,web}:latest` images confirmed untouched. Targets D3. Left the now-fully-
  superseded `loop-iter-31` worktree/branch in place (deletion is a destructive git op outside
  maker guardrails) for a human to clean up at their discretion. See iterations.md Iteration 39.)
  Earlier: Iteration 38: fixed checker V63/V64 against iteration 37's T014/T037 claim
  — gated the pre-migration backup on a new `migrations.is_upgrade_pending()` check (only backs
  up when the DB isn't already at head, fixing V63's every-boot-backup rotation-loss bug) and
  added 9 focused tests (6 for `backup.py`, 3 for the new gate) covering archive layout, pg_dump
  failure cleanup, rotation, and the gate itself against both mocks and a real fresh Postgres.
  `377 passed, 4 deselected, 0 failed` in isolated project `da-iter38`; live-verified the gate
  flips `True`→`False` across a real `alembic upgrade head` in isolated project `da-iter38b`.
  Found and flagged new debt DB24: D3's `checker-pass` (DB18/DB21 fixes) lives only on an
  unmerged `loop-iter-31` branch/worktree, never merged into `improvement` — the current branch's
  `Makefile`/`compose.yaml` still have the original unsafe-overwrite bug the checker verified as
  fixed. Also disclosed a low-severity self-corrected incident (a bare `docker compose run`
  briefly started the real `decision-assistant-db-1` container before failing harmlessly; stopped
  it back immediately). D1 stays pending. See iterations.md Iteration 38.)
  Earlier: Iteration 37: resolved DB22 per human decision — added
  `postgresql-client-16` (PGDG apt repo, exact-matched to `pgvector/pgvector:pg16`; the generic
  Debian package resolves to a mismatched major version whose `pg_dump` output a v16 `psql`
  can't restore, reproduced and fixed live) and a `./backups` host bind-mount into `api`. New
  `api/src/decision_assistant/backup.py` (`create_pre_migration_backup`) wired into `main.py`'s
  `lifespan` before `upgrade_to_head()`. Live-verified: fresh-boot backup, restart-triggered
  rotation (retention honored across 3 restarts), cross-mechanism restore via `scripts/restore.sh`
  against a T014-produced archive, `make test-api` 368 passed. Fixed a test-hygiene side effect
  found live (one test was writing a real backup to the host `./backups` dir on every test run —
  monkeypatched). T014 and T037 both marked `[X]`. Targets D1. See iterations.md Iteration 37.)
  Earlier: Iteration 36: rewired `Makefile`'s `backup`/`restore` targets to delegate
  to `scripts/backup.sh`/`scripts/restore.sh` (T037, partial); live-verified `make backup`/
  `make restore` round-trip in isolated project `decision-assistant-test-37` and reran
  `make test-api` (368 passed, 4 deselected) after a comment-only `main.py` edit. Discovered the
  in-container half of T037/T014 (startup auto-backup) cannot literally reuse
  `scripts/backup.sh`, since that script needs the HOST-side `docker` CLI/Compose, which the
  `api` container doesn't have — opened debt DB22 with three options, all requiring human
  escalation (new dependency, docker-socket mount, or a separate implementation) per AGENTS.md.
  tasks.md T037 stays `[ ]` (genuinely partial). Targets D1. See iterations.md Iteration 36.)
  Earlier: Iteration 35: marked tasks.md T035 `[X]` (bookkeeping fix per checker V59)
  and added `scripts/restore.sh` (T036), reversing `scripts/backup.sh` — restores `database.sql`
  via `docker compose exec -T db psql -v ON_ERROR_STOP=1` and `uploads.tar` via
  `docker compose exec -T api tar -xf -`. Live-verified end-to-end in isolated project
  `decision-assistant-test-36`: seeded DB rows + nested uploads files, backed up, mutated
  (extra row/table/file), restored, confirmed state matches the backup point exactly for tracked
  entries (extraneous post-backup objects are not deleted by restore, matching quickstart.md
  Section 5's delete-then-restore flow). Marked tasks.md T036 `[X]`. Isolated project torn down
  after; real `decision-assistant` containers/volumes confirmed untouched. Targets D1 (T035
  bookkeeping, T036). DB16 (T014's backup precursor) still open — T037 is the natural next
  increment. See iterations.md Iteration 35.)
  Earlier: Iteration 34: added `scripts/backup.sh` (T035) — produces
  `decision-assistant-backup-<UTC timestamp>.tar.gz` containing `database.sql` (pg_dump) and
  `uploads.tar` (uploads_data contents via the `api` container); live-verified end-to-end in
  isolated project `decision-assistant-test-34` (seeded DB row + nested uploads file round-tripped
  correctly through the archive). Fixed one real bug along the way (tar written from inside the
  container to a host path that doesn't exist there; fixed by streaming tar to stdout and
  redirecting on the host side). Did not touch `Makefile`'s existing `backup`/`restore` or add
  `scripts/restore.sh` — those are T036/T037, separate tasks, and changing `make backup`'s output
  format without a matching restore would break `make restore`. Targets D1 (T035); T014's backup
  precursor (DB16) still needs T037 to wire this script in. Isolated project torn down after; real
  `decision-assistant` project/images confirmed untouched. See iterations.md Iteration 34.)
  Earlier: Iteration 33: verified D4 already satisfied on `improvement` as-is, no code
  change — `docker compose config` shows no source bind-mounts for api/web, localhost-only ports
  for api/web/ollama, no db port published. See iterations.md Iteration 33.) Earlier: Iteration
  32: fixed DB21 — `Makefile`'s `test-api`/`test-web` now default to
  an isolated `-p decision-assistant-test` Compose project instead of the pinned real
  `decision-assistant` project, so the literal documented commands can no longer overwrite the real
  deployed `decision-assistant-api:latest`/`decision-assistant-web:latest` image tags; `test-api`
  also tears down the isolated project after running. Verified by running both LITERAL bare
  commands (not an isolated workaround — isolation is now built in): `make test-web` → `38 passed
  (11 files), 0 failed`; `make test-api` → `368 passed, 4 deselected, 0 failed`; real image
  timestamps unchanged before/after. Same worktree `loop-iter-31`, not yet merged. Targets D3.
  Earlier: Iteration 31: fixed DB18 — pinned `web`'s compose `build.target` (was
  defaulting to `web/Dockerfile`'s last stage, the npm-less nginx runtime), updated `make test-web`
  to build the `build` stage and run with `--no-deps`; verified `38 passed (11 files), 0 failed` in
  isolated `loop-iter-31-test` project, `docker compose config` default target unchanged
  (`runtime`), in worktree `loop-iter-31`. Targets D3. Earlier:
  Iteration 2: confirmed T001 had reverted on disk and reapplied the
  multi-stage `api/Dockerfile` in worktree `loop-iter-2`; Iteration 3: rewrote `web/Dockerfile`
  multi-stage build/nginx runtime in worktree `loop-iter-3`; Iteration 4: edited `compose.yaml`
  (removed api/web source bind-mounts, pinned ollama tag, dropped stale `PDF_PARSER`) in worktree
  `loop-iter-4`; Iteration 5: edited `compose.yaml` (127.0.0.1-bound ports for api/web/ollama,
  removed db port publish) in worktree `loop-iter-5`; Iteration 6: reconciled loop-iter-2..5 into
  `improvement` via sequential merges, deleted the worktrees/branches; Iteration 7: added nginx
  SPA-fallback config per DB2 in worktree `loop-iter-7`; Iteration 8: fixed web command/port/
  healthcheck mismatch per DB3 in worktree `loop-iter-8`, merged both 7+8 into `improvement`;
  Iteration 9: fixed DB3's healthcheck regression (localhost -> 127.0.0.1) in worktree
  `loop-iter-9`, merged into `improvement`; Iteration 10: extended root Makefile with
  install/start/stop/backup/restore targets per T005 in worktree `loop-iter-10`, merged into
  `improvement`; Iteration 11: blanked shared-default credentials in `.env.example` per T006 in
  worktree `loop-iter-11`, merged into `improvement`; Iteration 12: added Alembic revision 0012
  per T007 and fixed a pre-existing T001 regression (alembic/ excluded from the production image)
  in worktree `loop-iter-12`, merged into `improvement`; Iteration 13: fixed DB10 (checker V14's
  finding that `api`'s compose build had no `target:`, defaulting to the dev-extras `test` stage)
  by pinning `target: ${API_BUILD_TARGET:-base}` and updating `make test-api` to override it, in
  worktree `loop-iter-13`, merged into `improvement`; Iteration 14: added `CorpusRebuild`
  SQLAlchemy model per T008 in a new `workspace/rebuild_models.py` (models.py already over the
  500-line cap) in worktree `loop-iter-14`, merged into `improvement`; Iteration 15: added
  `citation_stale` to `DecisionEvidence` model/schema per T009, and fixed a pre-existing regression
  (tests/ excluded from the api image, `make test-api` silently ran zero tests since T003) in
  worktree `loop-iter-15`, merged into `improvement`; Iteration 16: added
  `disclosure_acknowledged_at` to `Workspace` model/schema per T010 in worktree `loop-iter-16`,
  merged into `improvement`; Iteration 17: fixed DB7 (checker V10's finding that `backup`/`restore`
  silently no-op against an already-populated DB) by adding `--clean --if-exists` to `pg_dump` and
  `-v ON_ERROR_STOP=1` to `psql` in worktree `loop-iter-17`, merged into `improvement`; Iteration 18:
  fixed DB12 (models.py over the 500-line cap) by splitting its 14 ORM classes into
  auth/workspace/ingestion/decisions/retrieval `models.py` files and updating 38 call sites' imports
  in worktree `loop-iter-18`, merged into `improvement`; Iteration 19: added `jobs/recover_and_requeue`
  per T011, removed superseded dead-code `ingestion/jobs.py`, in worktree `loop-iter-19`, merged into
  `improvement`; Iteration 20: fixed DB11 (and moot-resolved DB14) via a test-only `compose.test.yml`
  override, `make test-api` now genuinely exits 0 (364 passed, 4 deselected live_provider, 0 failed)
  in worktree `loop-iter-20`, merged into `improvement`; Iteration 21: fixed DB6 (wired
  `VITE_API_URL` as a real Docker build ARG) in worktree `loop-iter-21`, merged into `improvement`;
  Iteration 22: fixed DB5 (added redacted `make config` target) in worktree `loop-iter-22`, merged
  into `improvement`; Iteration 23: partially fixed DB13 (extracted 6 self-contained pieces out of
  evaluation/service.py, 1265->900 lines; EvaluationService class itself, ~800 lines, still needs a
  future mixin-based split) in worktree `loop-iter-23`, merged into `improvement`; Iteration 24:
  re-fixed DB5 (checker V38's two adversarial leaks: multi-line YAML block-scalar secret,
  `@`-embedded connection-string password) by replacing the sed pipeline with
  `scripts/redact_config.awk` in worktree `loop-iter-24`, merged into `improvement`; Iteration 25:
  re-fixed DB5 again (checker V40's remaining leaks: empty-username URL, `@`-containing username,
  plus a latent hyphen/dot key-class gap) by redacting the whole URL userinfo up to the last `@`
  before the path, and widening the secret-key character class, in worktree `loop-iter-25`, merged
  into `improvement`; Iteration 26: re-fixed DB5 again (checker V41's regression: password
  containing `/` or a space was left unredacted by iteration 25's char-class-excluding regex) with
  authority-aware bounding (`lastpos()` helper finds the last `/` to bound the authority, redacts up
  to the last `@` within it) in worktree `loop-iter-26`, merged into `improvement`; Iteration 27:
  re-fixed DB5 again (checker V42: the authority-bounding approach still leaked a `/`-containing
  password when the URL had no path, since that shape is textually identical to a path containing
  `@`) by reverting to a plain greedy `:\/\/.*@` match per V42's own leak-safety guidance, and added
  a checked-in fixture regression test (`scripts/fixtures/redact_config/`, `make
  test-config-redaction`) in worktree `loop-iter-27`, merged into `improvement`; Iteration 28:
  completed Phase 2's remaining tasks — T012 (`max_ingestion_attempts`/`max_evaluation_attempts`
  Settings fields), T013 (`validate_startup_config()` config-validation function), T014 partial
  (auto-migration wired into `lifespan` via `asyncio.to_thread`; pre-migration backup precursor
  blocked on unimplemented T035/T037, opened debt DB16), T015 (`diagnostics/` package skeleton) —
  in worktree `loop-iter-28`, merged into `improvement`; Iteration 29: fixed checker V46's two
  T014 regressions (`alembic/env.py`'s `fileConfig` silencing uvicorn's loggers when run in-process;
  `migrations.py`'s ini-path resolution breaking under a non-editable install), added
  `test_migrations.py`, live-verified against a fresh DB with the actual production image, in
  worktree `loop-iter-29`, merged into `improvement`; Iteration 30: completed Phase 3 (User Story 1)
  — T016 (`/health` version field via `importlib.metadata`), T017 (web UI version display on
  `Account.tsx`), T018 (`docs/install.md`) — in worktree `loop-iter-30`, merged into `improvement`;
  opened debt DB18 (`make test-web` broken since T002 — `web`'s compose service has no `target:`,
  always builds the npm-less nginx stage); incident during verification (unscoped `docker compose`
  command briefly touched the shared default project, contained with no data/image impact, see
  iterations.md Iteration 30 for full disclosure and M-021); see iterations.md)
- Isolation: worktree

## Roles
- Maker: produces work toward the criteria (/speckit-loop-run).
- Checker: independent, adversarial grader (/speckit-loop-check). MUST be a
  separate agent/session from the maker.

## Allowed tools / connectors
- Bash: `docker compose`, `make`, `alembic`, `pytest` (via `docker compose run --rm api pytest`),
  `npm`/`vitest` (via `docker compose run --rm web npm test`), `git`.
- Standard file read/write/edit tools for `api/`, `web/`, `specs/002-production-readiness/`,
  `.github/workflows/`, `docs/`, repo-root `compose.yaml`/`Makefile`/`.env.example`.
- No external MCP connectors or network calls beyond what the existing stack already makes
  (Docling model download at build time, configured model provider at runtime).

## Automation trigger
- Manual: `/speckit-loop-run` per iteration. Not wired to CI/scheduler.

## Guardrails
- Human sign-off required before done: true
- Comprehension debt tracked: true
- Open blocking debt blocks done: true

## State
- Phase: checked
- Last updated: 2026-09-27 (checker, iteration 104, V176-V178: no criterion was maker-ready. D2 stays checker-pass on re-check: 543 API passed, lint clean. D3 was not re-run because no web file changed. **DB72(a) and DB73 are verified fixed**: an independent mutant for each fails exactly its new test. New debt **DB76** (low): `_latest_rebuild` orders by the transaction-start `created_at`, so commit order can invert. D1-D13 are all checker-pass.)
  Earlier: 2026-09-27 (maker, iteration 104: **DB72(a) and DB73** fixed — the manual rebuild
  retry takes the provider-switch lock, re-checks its precondition under it, and dispatches with the
  factory that exists after the lock; 2 new tests, each killed by a named mutant. Gates:
  `make test-api` **543 passed, 4 deselected** exit 0, `make lint-api` exit 0, focused four-file run
  **37 passed**. No done-criterion was targeted, so D1-D13 keep their statuses. New debt **DB75**
  (low: a test races on `startup_redispatch_tasks`, which prunes finished tasks). Awaiting
  `/speckit.loop.check`.)
  Earlier: 2026-09-27 (checker, iteration 103, V172-V175: no criterion was maker-ready. D2 and D3 stay checker-pass on re-check: 541 API, 79 web, lint clean. DB72(b) and DB72(c) pass; the mutant and a forced-failure `make test-api` behave as claimed. **DB72(a) fails (V173):** the retry route still dispatches with the provider factory that `Depends` resolved before the lock, so a retry queued behind a confirmed switch runs with the old bundle under the new settings. DB72 is reopened. New low debt: DB73 (concurrent retries give a 500) and DB74 (shared-project `down -v` in `lint-api`/`test-web`).)
  Earlier: 2026-09-27 (maker, iteration 103: **DB72** (a), (b) and (c) addressed — the retry route takes the process-wide provider-switch lock before inserting its `pending` rebuild; two route-level tests pin the lock call sites and a mutant deleting both calls fails 2 of 2; `test-api`/`test-web`/`lint-api` now clean up their volumes on a failing run and still exit non-zero. Gates: `make test-api` 541 passed/4 deselected exit 0, `make lint-api` exit 0, `make test-web` 18 files/79 passed exit 0. Awaiting `/speckit.loop.check`.)
  Earlier: 2026-09-27 (checker, iteration 102, V166-V171: no criterion was maker-ready. D1, D2, D3 and D8 stay checker-pass on re-check: 539 API, 79 web, lint clean, `make test-backup` PASS, and the V160 restart-removed mutant now fails the harness. DB67, DB68, DB69 and DB70 are verified fixed. DB71 stays open for a human decision. New debt: DB72 (low: the retry route bypasses the switch lock, the lock has no route-level test, `test-web` leaks volumes on failure). All `checker103*` projects, volumes and images are torn down.)
  Earlier: 2026-09-27 (maker, iteration 102: DB67, DB68, DB69 and DB70 are all addressed and
  the gates are green — `make test-api` 539 passed/4 deselected exit 0, `make lint-api` exit 0,
  `make test-web` 18 files/79 passed exit 0 (its new `down -v` removed the three project volumes),
  the web production build (`tsc -b && vite build`) exit 0, `make test-backup` PASS. Mutation
  evidence: the restore-restart mutant fails the new pooled-backend assertion (`make` exit 2) and
  the no-op lock mutant fails `test_provider_switch_lock.py`; both files were restored afterwards and
  the lock test re-run green. No done-criterion was targeted, so D1-D13 keep their recorded
  statuses — this iteration exists to close debt, not to move a criterion. New debt **DB71** (the
  DB51 behavioural probe could not be reproduced in this environment; the regression weight sits on
  the pooled-backend assertion). Awaiting `/speckit.loop.check`.)
  Earlier: 2026-09-27 (checker, iterations 97-101, V158-V165: no criterion was maker-ready. D1, D2, D3 and D8 stay checker-pass on re-check: 538 API, 79 web, lint clean, `make test-backup` PASS. The fixes for debt rows DB51, DB52, DB53, DB56, DB57, DB61, DB63, DB64, DB65 and DB66 are verified. DB51 is verified live with a warmed-pool probe: the mutant gives 500, the real restore gives 401. New debt: DB67 (medium, three source files over the 500-line cap), DB68 (low, a switch-guard race), DB69 (low, the DB51 regression assertion is vacuous and `make test-web` leaks volumes), DB70 (low, two doc gaps). All `checker102*` projects, volumes and images are torn down.)
  Earlier: 2026-09-27 (maker, iterations 97-101: the open debt rows **DB51, DB52, DB53, DB56,
  DB57, DB61, DB63, DB64, DB65, DB66** are all addressed; none of the thirteen done-criteria was
targeted, and D1/D2/D3/D5-D13 keep their recorded statuses. Worth the checker's attention rather
than a green-suite claim: DB63(a) is a real product behaviour change (a PDF queued longer than
`max(600s, 20 × parse budget)` now fails with `pdf_parse_timeout`), DB61(b) sets `propagate = False`
on uvicorn's loggers, and DB51's fix restarts the `api` container after every restore. Isolated
projects used and torn down: `decision-assistant-test`, `decision-assistant-test-backup`,
`decision-assistant-bkdebug`. Earlier: 2026-09-26 (checker, iterations 95-96, V153-V157: D1 and D9 are checker-pass. D2 and D3 stay checker-pass on re-check (529 API, 78 web). T072 was independently re-run on a clean checkout (`checker97qs`, torn down). DB62 is verified fixed. DB51 still reproduces, although iteration 96 said it did not. New debt: DB65 (low), DB66 (low).)
  Earlier: 2026-09-26 (maker, iteration 96: **T072 executed** — quickstart.md all 8 sections run live against an isolated clean checkout (`decision-assistant-qs`), with every section's evidence recorded in iterations.md Iteration 96. `grep -c '^- \[ \]' tasks.md` = 0. Real `decision-assistant-{api,web}:latest` image IDs unchanged (`86d9b6719658`/`6773f0c063e7`); throwaway stack, images, and temp files removed. Maker evidence only — the checker must re-verify T051 and confirm the T072 live run. Earlier: 2026-09-26 (maker, iteration 95: T051 fixed — the disclosure reports both providers plus per-provider remote flags and a mixed-configuration test pins the correct destination. Gates: `make test-web` 18 files/78 passed, `make test-api` 529 passed/4 deselected, `make lint-api` clean, web build (`tsc -b && vite build`) clean. Maker belief only; the checker must re-run V146's mixed-configuration break. Earlier: 2026-09-26 (checker, iteration 94, V145-V152: D2/D3 stay checker-pass (529 API, 77 web, lint clean). Task verdicts under D1: T051 checker-fail (disclosure names the wrong destination for mixed provider configurations, high); T052/T053/T067/T068/T069 pass (medium), T071 pass (low). DB64 opened (low, uninstall doc names an undeclared volume). D1 and D9 stay pending.)
  Earlier: 2026-09-26 (checker, iteration 93, V142-V144: D11 checker-pass (high). The timed-out parse reclaims CPU and memory live, and V139's OOM repro no longer reproduces. DB60 is verified fixed. DB62 is reopened for 3 literal §6 command defects (low). DB63 opened for residuals (low).)
  Earlier: 2026-09-26 (maker, iteration 93, DB60/D11: the PDF parse moved into a killable child process with its own budget and a process-wide slot pool, plus an `api` restart policy; 525 API tests pass, lint clean, and the timeout integration test asserts no parse child survives. D11 → `maker-ready` for a live quickstart §6 run.)
  Earlier: 2026-09-26 (checker, iterations 87-92, V138-V141: D10 checker-pass (medium); D11 checker-fail because timed-out Docling threads keep running and 14 of them plus one upload OOM-killed the API, which needed a manual restart (DB60, high); D2/D3 stay checker-pass on re-check (510 API, 64 web). New debt: DB60 (high), DB61 (low), DB62 (low). Isolated `checker93`/`checker93t`/`checker93w` torn down.)
  Earlier: 2026-09-26 (maker, iteration 88: T059 — authenticated diagnostics download in the web client plus a `DiagnosticsDownload` component on the settings page, 6 new tests; `make test-web` **14 files, 59 passed**, exit 0 (also runs `tsc -b`); two jsdom harness traps found and fixed. **D10 → `maker-ready`** and **D11 → `maker-ready`** (both pending their live quickstart Sections 7 and 6 runs by the checker). D1 stays `pending`: 16 tasks remain (US5 needs escalation; T050/T047 are a provider change needing escalation; the rest are web/docs/polish).)
  Earlier: 2026-09-26 (maker, iteration 87: T062 + T065 — real-dispatch parse-timeout integration test (timed-out job `failed pdf_parse_timeout`, next document `completed` on the same loop), new `tests/support/ingestion_fixtures.py`, T065 confirmed as existing code; literal `make test-api` **480 passed, 4 deselected**, exit 0, `make lint-api` exit 0 first try.)
  Earlier: 2026-09-26 (maker, iteration 86: T058 + T060 — authenticated in-memory diagnostics bundle route with download headers and a real DB-revision read, 2 tests, auth mutant exact; T060's no-telemetry grep recorded as evidence; literal `make test-api` **479 passed, 4 deselected**, exit 0, `make lint-api` exit 0 after removing one unused import.)
  Earlier: 2026-09-26 (maker, iteration 85: T046 + T049 — upload disclosure gate enforced in `submit_uploads` (409 `disclosure_not_acknowledged`), fixtures and both HTTP scripts acknowledging first; literal `make test-api` **477 passed, 4 deselected**, exit 0, zero failures, `make lint-api` exit 0.)
  Earlier: 2026-09-26 (maker, iteration 84: DB55 fixed — incremental UTF-8 probe decode with a completeness flag, the checker's V136 probe turned into a repo regression test killed by the pre-fix mutant; literal `make test-api` **475 passed, 4 deselected**, exit 0, `make lint-api` exit 0, DB56 open.)
  Earlier: 2026-09-26 (checker, iterations 79-83, V135-V137: no criterion was maker-ready. D2 stays checker-pass on re-check (473 passed, lint exit 0). V136 fails T063: DB55 (medium), a UTF-8 boundary false rejection. V137 is uncertain on log-scrubbing completeness: DB56 (low). Isolated `checker83t`/`checker83l`/`checker83p` torn down.)
  Earlier: 2026-09-26 (maker, iteration 83: T061 + T063 + T064 — pre-parse upload validation (magic bytes, `max_pdf_pages`, wired ahead of the frozen `parse_document`), 8 tests, per-check mutant attribution; the batch gate caught and the maker fixed a settings-stub regression, then literal `make test-api` **473 passed, 4 deselected**, exit 0 and `make lint-api` exit 0. D1 stays `pending`: 23 tasks remain; D11 needs T062/T065, D10 needs T058-T060, D9 needs T049/T046/T047/T050-T053 plus all of US5 (auth escalation).)
  Earlier: 2026-09-26 (maker, iteration 82: T055 + T057 — diagnostics bundle with an allowlist plus two independent leak guards, split into a pure assembler and an async builder, plus `migrations.current_db_revision`; 7 tests, per-test mutation attribution, literal `make test-api` **465 passed, 4 deselected**, exit 0, `make lint-api` exit 0.)
  Earlier: 2026-09-26 (maker, iteration 81: T048 — provider-disclosure `GET`/`POST .../ack` routes, owner-scoped, plus `providers/disclosure.py` and an idempotent acknowledgement; 7 new tests, 5 of 7 killed by combined mutants; literal `make test-api` **458 passed, 4 deselected**, exit 0; `make lint-api` exit 0 after an unused-import fix.)
  Earlier: 2026-09-26 (maker, iteration 80: T054 + T056 — rotating, secret-scrubbed file logging (`diagnostics/logging.py`, 4 new `Settings` fields, wired from `create_app`), 9 new tests, 2 mutation checks killed the intended tests, `make lint-api` exit 0, literal `make test-api` **451 passed, 4 deselected**, exit 0 on the final tree, real images unchanged. D1 stays `pending`: 29 tasks remain.)
  Earlier: 2026-09-26 (maker, iteration 79: T038 — new `docs/backup-restore.md`, linked from `docs/install.md`; T038 `[X]` and maker-ready. Docs-only, so no test gate was applicable. D1 stays `pending`: 31 tasks remain in Phases 7-11, and US5/T042 (auth) needs an escalation before it can start.)
  Earlier: 2026-09-26 (checker, iterations 77-78, V131-V134: D2 and D12 are checker-pass. New debt: DB54 (medium, D12's structural limit), accepted by human 2026-09-26 and closed. Human decision, 2026-09-26: SC-006 will not be re-run. Isolated `checker78t`/`checker78p` projects torn down.)
  Earlier: 2026-09-26 (checker, iterations 68-76, V124-V130: D8 and D13 are checker-pass; D2 and D12 are checker-fail. New debt: DB49 (medium, an order-dependent abort test that breaks `make test-api`), DB50 (high, explicit-value verification is passage-wide, so injected text can support fabricated dates; needs a human decision), DB51 (medium, a 500 right after restore), and DB52 (low).)
  Earlier: 2026-09-26 (checker, iterations 64-67, V121-V123: D2 and D7 stay checker-pass on re-check, with `make test-api TEST_PROJECT=checker67t` giving 430 passed. V122 is uncertain and opens DB44 (low): only the `RebuildAborted` path zeroes discarded progress. V123 fails T033's doc claim of a web rebuild banner that does not exist and opens DB45 (low). D8 stays pending, because T034 is the automated half only and quickstart Section 5 has not run live. No criterion was maker-ready. The isolated `checker67t` project was torn down.)
  Earlier: checker, iteration 63, V119-V120: D7 checker-pass. DB43 is verified fixed live on both the provider-outage abort and the partial abort after 4/6 documents, and the HTTP retry recovers to `completed 6/6`. `make test-api TEST_PROJECT=checker63t`: 428 passed. Isolated `checker63` stack torn down.)
  Earlier: checker, iteration 62, V113-V118: D7 checker-fail. DB40, DB41, and DB42 are verified fixed live. New DB43 (high): a partially failed rebuild commits an emptied corpus that neither retry path can restore. `make test-api TEST_PROJECT=checker62t`: 427 passed. Isolated `checker62` stack torn down.)
  Earlier: checker, iteration 61, V108-V112: D7 checker-fail. Rebuild reads stay unchanged in-flight (pass), but the reshaped-chunk case drops decisions from timelines and nulls quotes (DB40 residual, live), the rebuild status is invisible while running (new DB41, high), and failed-ingestion documents are deleted (new DB42, medium). `make test-api TEST_PROJECT=checker61t`: 422 passed. Isolated `checker61` stack torn down.)
  Earlier: maker, iteration 61: resolved DB39 — human decision: delete orphaned
  decisions in `0015` before `SET NOT NULL`, rather than folding `0014`/`0015` into one revision.
  `0015_decisions_workspace_id.py` adds `DELETE FROM decisions WHERE workspace_id IS NULL` after
  the backfill. Live repro (seed orphan at `0014`, `alembic upgrade head`) now succeeds, orphan
  row confirmed deleted. `make test-api` not yet re-run against this change. Not independently
  checker-verified. DB40 (timelines/retrieval/answering drop rebuilt decisions) still open; human
  decision: expand T031 to re-link `document_version_id`/`passage_id` to the new rows after a
  rebuild, rather than making each reader tolerate `NULL`.
  Earlier: checker, iteration 60, V104-V107: DB37 pass; DB38 API surface pass; `0015` upgrade fails on orphaned decisions (new DB39, medium); timelines drop rebuilt decisions (new DB40, high). D7 stays pending. Earlier: maker, iteration 60: resolved DB37 (stop deleting `retrieval_traces`
  from the rebuild scope, human decision) and DB38 (add `decisions.workspace_id`, revision
  `0015_decisions_workspace_id`, human decision). `decisions/service.py` now scopes by
  `Decision.workspace_id` directly and outer-joins `Passage` for evidence. Schema/web types and
  every affected test fixture updated to match. `make test-api` 412 passed, `make test-web`
  build+45 passed. D7 stays `pending` — T027-T031 (integration test, coordinator lifecycle,
  lifespan wiring, endpoint, `citation_stale` stamping) remain. Not independently
  checker-verified. See iterations.md Iteration 60.)
  Earlier: maker, iteration 59: implemented T026 — `coordinator.py`'s
  `truncate_corpus_derived_tables` uses `DELETE`, not `TRUNCATE` (independently avoiding V103's
  `TRUNCATE`-ignores-`SET-NULL` finding, reasoned from the schema before seeing the checker's
  verdict — see iterations.md Iteration 59's risk #1), and the new `test_corpus_rebuild.py` proves
  the decision/evidence survive with a nulled FK. This does NOT close DB37 (`retrieval_traces`
  deletion cascades away `conversation_messages`/`question_answers`) or DB38 (nulled
  `document_version_id` drops the decision from workspace-scoped `GET /decisions` and 404s its
  detail route) — both still need a human schema decision per their debt.md rows, opened by the
  checker against iteration 58. D7 stays `pending`; T026 is `[X]` but T028's actual coordinator
  cannot be finished honestly until DB37/DB38 are resolved. `make test-api` 412 passed. See
  iterations.md Iteration 59.)
  Earlier: checker, iteration 58: V102 pass, 0014 schema layer is correct. V103 FAIL, DB34 is not
  resolved as the D7 blocker: `TRUNCATE` ignores SET NULL, and the planned T026 `TRUNCATE` would
  wipe decisions and conversations. New high debt DB37 (conversation_messages/question_answers
  CASCADE from retrieval_traces) and DB38 (decisions have no workspace_id, so nulled decisions
  become 404/invisible). D7 stays `pending`; no criterion was maker-ready. Next step needs human
  schema decisions.
  Earlier: maker, iteration 58: fixed DB34's schema blocker for D7 — revision
  `0014_decision_setnull_fk`, `decisions/models.py` updated to match, live-verified a decision
  survives its `document_version_id` row's deletion with the FK nulled. `make test-api` 411
  passed. D7 stays `pending` (T026-T031 not implemented); DB34 moved from "open, human-approved"
  to "schema fix resolved, awaiting checker". See iterations.md Iteration 58.)
  Earlier: maker, iteration 57: **DB35 verified fixed** — human commit `281a525`
  caches the dependency/model layer independently of source; a source-only rebuild now takes 6.17 s
  (base) / 7.15 s (test) with that layer `CACHED`, versus 5–15 min before. `make test-api` 410
  passed, D5 `alembic upgrade head` → `0013_eval_run_attempt_count (head)` on a fresh DB. Opened
  **DB36** (medium): `docling-core` floats (2.98.1 → 2.99.0 across two builds of the same commit)
  and sits on the parser path the corpus profile only guards by the `docling` distribution version.
  **DB34 is unblocked for build work** — the human approved option (a); the migration is the next
  step for D7.) Earlier: maker, iteration 56: scoped **D7**, wrote no code — **blocked on DB34**: the
  schema's `ondelete="CASCADE"` on `decisions.document_version_id` and
  `decision_evidence.passage_id` means US3's truncate scope would destroy the very decisions D7
  requires to survive. Needs a human decision on the schema shape (recommended: nullable columns +
  `ON DELETE SET NULL`, new revision 0014, plus a `data-model.md` correction). Separately recorded
  **DB35** — the `api/Dockerfile` layer order — as the highest-leverage fix before starting the
  D7–D13 batch, since every one of those ~35 tasks pays a 5–15 minute rebuild.) Earlier: checker, V101: D6 PASS high on a live isolated production stack; opened DB33 low for the quickstart §3 timing wording. D1 and D7-D13 remain pending.) Earlier: maker, iteration 55: DB32 resolved by human decision — evaluation is
  development-only; docs updated in quickstart §3, README, docs/install.md, AGENTS.md, and the API
  now distinguishes a missing benchmark (`evaluation_unavailable`) from a broken one
  (`dataset_invalid`), with a unit test. Earlier: maker, iteration 54: D6 executed live and moved to `maker-ready`
  (SIGKILLed ingestion requeued and completed, no manual resubmission); `main.py` now logs startup
  recovery counts so quickstart Section 3's log-grep step can pass; DB32 opened — evaluation
  datasets are not in the production image, so Section 3's evaluation repeat is not runnable.)
  Earlier: checker, V100: iteration 52 DB29 UI half PASS high; DB29 resolved (V96 + V100). D6 and D1 remain pending. Earlier: checker, V99: DB31 PASS high, resolved. The two-session lock test kills the no-lock mutant, and a real-HTTP probe (2 and 5 concurrent retries) gives exactly one 202 and one dispatch. D6 and D1 remain pending.) Earlier: maker, iteration 53: fixed DB31 — `retry()` takes `SELECT ... FOR
  UPDATE` on the document row; new two-session concurrency test in
  `api/tests/integration/test_documents_retry_concurrency.py`, no-lock mutant killed;
  `make test-api` 407 passed, isolated project, real images unchanged. DB31 is maker-ready for
  checker verification. No task IDs moved; D6 still needs a live quickstart Section 3 run.)
  Earlier: maker, iteration 52: fixed V97 — `Workspace.tsx`'s `handleRetry`
  reads the open document id from `openDocumentIdRef` instead of a stale `sourceDocument`
  closure, re-checked after the refresh fetch; test fixtures split out to
  `web/src/test/documentFixtures.ts`, V97 tests in `Workspace.retryRefresh.test.tsx`. Two
  in-container mutants killed; `make test-web` 45 passed; web build clean. DB29's UI half is
  maker-ready for re-check; D6 stays pending for quickstart.md Section 3. See iterations.md
  Iteration 52.) Earlier: checker, V96-V98: DB29 backend PASS high; DB29 UI FAIL high: stale `sourceDocument` closure in `handleRetry` reopens a dialog the user closed during an in-flight retry; DB29 stays open. DB30 PASS high, resolved. Opened DB31 low: concurrent retry race has no lock. D6 stays pending; D1 pending.) Earlier: maker, iteration 51: fixed DB29 (V94) — `retry()` rejects unless
  the document's LATEST job is `failed`; `Workspace.tsx` refreshes the open detail after
  retry — and DB30 (V95) — split `test_documents_api.py` into 3 files, all under 500 lines.
  Full suite `make test-api` 406 passed, `make test-web` 42 passed, `npm run build` clean.
  Ready for checker on DB29/DB30. See iterations.md Iteration 51.)
  Earlier: checker, V93-V95: T024 PASS high. T025 FAIL high: open detail view keeps Retry enabled after a successful retry, and backend accepts a second retry while the first job is pending (two concurrent jobs, same version); fix by refreshing the open detail after retry and rejecting retry when the latest job is not `failed`. V95 FAIL high: `test_documents_api.py` 538 lines, above the 500-line limit; split it. T025 must be reopened in tasks.md by the maker. D6 stays pending; D1 pending. Earlier: maker, iteration 50: implemented T024 (`DocumentDetail` API fields)
  and T025 (detail-view retry UI; list-view half already existed). Full suite `make test-api`
  404 passed, `make test-web` 41 passed, `npm run build` clean. Real containers/images
  confirmed unchanged. Ready for checker on T024/T025. See iterations.md Iteration 50.)
  Earlier: checker, V92: DB28 fix PASS high, 5 mutants killed, suite 402 passed; DB28 resolved. D6 stays pending: T024/T025 open, quickstart Section 3 not yet executed. D1 pending. Earlier: maker, iteration 49: fixed DB28 — `recover_and_requeue` now
  stamps a terminal timestamp (`finished_at_field`) alongside the error field on the
  terminal-`failed` path, for both `IngestionJob` and `EvaluationRun`; added the lifespan
  integration test DB28 specifically asked for (plus its ingestion parity). Full suite `402
  passed, 4 deselected, 0 failed`. Ready for checker on DB28. See iterations.md Iteration 49.)
  Earlier: checker, V89-V91: T022 pass medium, T023 pass medium, D5 re-confirmed at `0013` high; opened DB28 low for surviving `error_field` mutant. D6 remains pending: T024/T025 open, quickstart Section 3 not yet executed. Earlier: maker, iteration 48: implemented T023 per human decision — new
  Alembic revision `0013_eval_run_attempt_count`, `recover_and_requeue`'s `error_field` param,
  `EvaluationRun` startup sweep in `main.py` redispatching via `EvaluationBackgroundRunner` to
  a genuine `completed` terminal state (real dispatch path, not a stub — matches T020's
  precedent). Full suite `398 passed, 4 deselected, 0 failed`; migration verified clean. Ready
  for checker on T023. See iterations.md Iteration 48.) Earlier: maker, iteration 47: T022
  confirmed already satisfied by existing
  code (job row persisted before every `background_tasks.add_task` dispatch), added a
  regression test proving it. T023 escalated to the human, not implemented — needs an Alembic
  migration adding `EvaluationRun.attempt_count` (and resolving the `failure`-vs-`error` field
  name mismatch `recover_and_requeue` expects), which is a schema change per AGENTS.md's
  ask-first rule. Full suite `395 passed, 4 deselected, 0 failed`. Ready for checker on T022;
  T023 blocked on human decision. See iterations.md Iteration 47.) Earlier: checker, iteration
  46, see V86-V88: DB27 PASS (3 mutants killed, `pending` sweep safe under `--workers 1`) — resolved. T020 PASS (real dispatcher, terminal `completed` for `running` and `pending` seeds). T021 PASS re-confirmed. `make test-api` 394 passed, exit 0. Also closed DB19 row per V82 (bookkeeping missed last check). No D-id status changed; D1 stays pending; D6 still needs T022/T023 plus quickstart Section 3 run. Isolated `checkeri46` torn down.) Earlier: (maker, iteration 46: fixed checker V84/V85 — DB27 (sweep now
  covers `pending` too, plus `create_task` refs held on `application.state`) and T020
  (rewritten to run the real redispatch path to a genuine terminal state). Full suite `394
  passed, 4 deselected, 0 failed`. Ready for checker on DB27/T020. See iterations.md Iteration
  46.) Earlier: checker, iterations 44-45, see V82-V85: DB19 PASS (dangling `docs/backup-restore.md` links gone; `make backup`/`make restore -- <backup-file>` guidance matches Makefile) — resolved. T019 PASS. T021 PASS literal scope (`make test-api` 393 passed; 3 wiring mutants killed; real-dispatcher E2E reached terminal) but DB27 opened (high, blocks D6): a requeued job left `pending` by a crash before ingest starts is never swept again — reproduced across two restarts; also untracked `create_task` refs. T020 FAIL: test asserts `pending` + stub dispatch call, never the task's required terminal state; maker should unmark T020 `[X]` and add a terminal-state assertion with the real dispatcher + fake providers. No D-id status changed; D1 stays pending. Isolated `checkeri45` torn down; real containers untouched.) Earlier: checker, iteration 43, see V78-V81: DB8 PASS (both lifespan-wiring mutants killed; percent-encoded/any-spelling placeholder rejected; parse error leaks no secret; full suite 389 passed) — resolved. DB15 PASS (literal AGENTS.md commands incl. new build step, 8 passed) — resolved. DB26 PASS (real `.env` off placeholder, old password rejected over network, real stack healthy, `/health` 200) — resolved. DB19 FAIL: V75's 4 findings fixed, but install.md now links nonexistent `docs/backup-restore.md` (unbuilt T038). No D-id status changed; D1 stays pending. Isolated `checkeri43` project torn down; real images/containers unchanged.) Earlier: maker, iteration 43: fixed every V73-V77 checker-fail — DB15,
  DB19, DB8 (mutant-kill tests + robust URL-credential comparison via `sqlalchemy.engine.make_url`),
  and DB26 (real DB password rotated per human decision, live-verified against the actual
  deployment, not an isolated project). Full suite `389 passed, 4 deselected, 0 failed`. No
  D-id status changed; D1 stays pending (50 unchecked tasks, unaffected by this debt-focused
  iteration). Ready for checker on DB8/DB15/DB19 (DB26 is a one-time environment action,
  already live-verified end-to-end, not really re-checkable the way code is — the checker
  can confirm the real stack still boots and the rotated credential isn't the placeholder).
  See iterations.md Iteration 43.) Earlier: checker, iterations 41-42, see V73-V77: DB17 PASS (resolved). DB15 FAIL (documented single-file command has no build step; tests stale image). DB19 FAIL (install.md treats `DATABASE_URL` as optional, misattributes placeholder, omits new guard). DB8/T045 FAIL: guard-call mutant survives full suite (383 passed), exact-string match bypassable, and real `.env` uses the exact placeholder so the real stack will no longer start (opened DB26, medium, needs human). DB20 staging PASS for literal scope. No D-id status changed; D1 stays pending (50 unchecked tasks). Isolated `checkeri42` project and image removed; real repo files untouched.) Earlier: maker, iteration 42: resolved DB20 (staged
  `specs/002-production-readiness/` per human decision, not committed) and DB8 (implemented
  T045, now `[X]` — startup guard rejects a missing `AUTH_JWT_SECRET`/placeholder
  `DATABASE_URL` before any DB access, per human's explicit "startup guard now" choice).
  Live-verified: direct probe against the real built image confirms both DB8 failure modes
  are rejected and real config passes; full suite `383 passed, 4 deselected, 0 failed`, zero
  regressions. Also cleared an environment-only Docker disk-full blocker with user approval.
  No D-id status changed. Ready for checker on DB8; DB20 is a staging action, not really
  checker material. See iterations.md Iteration 42.) Earlier: maker, iteration 41: closed 4
  open debts per explicit user request ("for the remaining debts") — DB15/DB17/DB19 fixed
  and live-verified (full suite 383 passed, literal new AGENTS.md single-file command
  verified against the new test file), DB16 bookkeeping-closed (underlying gap already
  checker-verified in iterations 37/38/40). No D-id status changed — this iteration targeted
  debt.md, not the done-criteria table. Ready for checker on DB15/DB17/DB19 (DB16 needs no
  re-check, it only closes out prior already-checker-verified work). See iterations.md
  Iteration 41.) Earlier: checker, iterations 39-40, see V70-V72: D3 → checker-pass (literal `make test-web` on `improvement`), D2 reconfirmed with the literal command; DB24 resolved. V68 fix PASS: 3/3 main.py mutants (no gate / reorder / swallow) killed by the new lifespan tests. V72: undisclosed stray empty-DB pre-migration archive in the real repo `./backups` from the maker's iteration 39/40 window, opened as DB25 (low). D1 stays pending (remaining tasks unchecked). Orphan `loop-iter-31` worktree/branch safe to remove at human discretion.) Earlier: maker, iteration 40: fixed V68 (lifespan gate/order untested) — 2
  new tests in test_app.py, full suite 379 passed. Ready for checker.) Earlier: maker,
  iteration 39: fixed DB24 (D3) — hand-ported DB18/DB21 onto `improvement`, literal bare
  `make test-api`/`make test-web` both exit 0, real project untouched. Ready for checker. See
  iterations.md Iterations 39-40.) Earlier: checker, iteration 38, see V67-V69: V63 fix PASS — backup now gated on pending migrations, live-verified (no-op restarts skip; forced 0011→0012 backs up true pre-migration state; missing pg_dump blocks startup and migration). V64 fix FAIL (partial) — backup.py/is_upgrade_pending covered, but lifespan gate/order has no test (V68). D3 → checker-fail: DB24 confirmed, `make test-web` fails on `improvement` (V69). `make test-api` 377 passed. Real project untouched. D1 stays pending.) Earlier: maker, iteration 38: fixed checker V63/V64 — `is_upgrade_pending`
  gate plus 9 focused tests, live-verified against a real fresh Postgres in isolated project
  `da-iter38b` and the full suite (377 passed) in `da-iter38`. Flagged new debt DB24 (D3's
  checker-pass fixes unmerged into `improvement`, see iterations.md Iteration 38) and a disclosed
  self-corrected incident. Ready for checker.) Earlier: checker, iteration 37, see V63-V66: FAIL on T014/T037 as claimed complete — (V63) `create_pre_migration_backup` runs on EVERY boot, not only when migrations are pending; live repro with retention 2 showed the only archive actually taken before a migration rotated away after 2 no-op restarts (default 5 → same loss after 5 restarts); (V64) `backup.py` has zero focused tests (only monkeypatched out in test_app.py). Both route back to maker; T014/T037 `[X]` marks are not checker-backed. PASS: D4 re-verified with new data bind-mount (V65); `make test-api` 368 passed, pg_dump 16.15 in image, archive layout matches scripts/backup.sh, no maker residue, real project untouched (V66). New low debt DB23 (Linux root-owned `./backups` bind source, unverified on macOS). D1 stays pending.) Earlier: maker, iteration 37: resolved DB22 (postgresql-client-16 via PGDG,
  `./backups` bind-mount, `backup.py`, wired into `lifespan`); T014 and T037 both marked `[X]` —
  see iterations.md Iteration 37. Flagging for checker: D4's own verification text is now stale
  (api.volumes gained a non-source bind-mount) and needs independent re-confirmation, not a diff
  against the old wording. Ready for checker.) Earlier: checker, iteration 36, see V61/V62:
  `Makefile`'s `backup`/`restore`
  targets independently confirmed to delegate to `scripts/backup.sh`/`scripts/restore.sh`
  (minimal diff matches claim exactly, nothing else in the Makefile changed). Independently
  reproduced the full `make backup`→mutate→`make restore` cycle from scratch in a fresh isolated
  stack (`COMPOSE_PROJECT_NAME=checkeri36`), mutating more destructively than the maker's own
  test (deleted both seeded upload files outright, added a conflicting table and a 3rd DB row):
  exit 0 both commands, DB rows restored to exactly the backup point, deleted upload files fully
  recreated, extraneous objects correctly left in place. `main.py`'s `lifespan` change confirmed
  comment-only (zero executable-line diff). DB22 independently verified as a genuine blocker, not
  an overstated one: read `api/Dockerfile` (no `docker` CLI, no `pg_dump` client) and
  `compose.yaml`'s `api.volumes` (named volume only, no docker-socket mount) directly — confirms
  `scripts/backup.sh`'s `docker compose exec` calls truly cannot run inside the `api` container as
  built/composed today. Real project images/containers confirmed unchanged before/after; isolated
  project torn down. No done-criterion status changed (D1 stays correctly `pending`; T037 remains
  genuinely partial, and DB22 needs a human decision before the maker can proceed on the
  in-container half).) Earlier: maker, iteration 36: rewired `make backup`/`make restore` to
  `scripts/backup.sh`/`scripts/restore.sh` (T037 partial), opened DB22 (in-container backup
  blocked pending human architecture decision) — see iterations.md Iteration 36. Ready for
  checker.) Earlier: checker, iteration 35, see V60: `scripts/restore.sh` (T036)
  independently reproduced from scratch on `improvement` at `3e2f32f` (untracked tree, no
  worktree, matching maker's approach per DB20). Confirmed `tasks.md` T035/T036 both now `[X]`
  (V59's checkbox finding closed). Booted fresh isolated stack (`COMPOSE_PROJECT_NAME=checkeri35`),
  seeded DB rows + upload files, ran literal `scripts/backup.sh`, then mutated more aggressively
  than the maker's own test — inserted an extra DB row, added a conflicting table, and **deleted
  both originally-seeded upload files entirely** (not just added extras) — then ran the literal
  unmodified `scripts/restore.sh`: exit 0, DB rows restored to exactly the backup point, both
  deleted upload files fully recreated from the archive with original content, extraneous
  DB table/upload file correctly left in place (additive restore, matches quickstart.md Section 5's
  delete-then-restore flow). Real project images/containers confirmed unchanged before/after;
  isolated project torn down. No done-criterion status changed (D1 stays correctly `pending`;
  T037 — wiring `scripts/backup.sh` into `main.py`'s pre-migration call and `make backup` — and the
  rest of tasks.md remain outstanding).) Earlier: maker, iteration 35: marked tasks.md T035 `[X]`,
  added `scripts/restore.sh` (T036), live-verified end-to-end in isolated project
  `decision-assistant-test-36` — see iterations.md Iteration 35. Earlier:
  checker, iteration 34, see V59: `scripts/backup.sh` (T035)
  independently reproduced from scratch on `improvement` at `3e2f32f` (untracked tree, no
  worktree, matching maker's approach per DB20) — script read verbatim, matches claim exactly.
  Booted isolated `db`+`api` (`COMPOSE_PROJECT_NAME=checkeri34`), hit and fixed the same
  password-mismatch the maker's log described, seeded a DB table + nested upload files, ran the
  literal unmodified script: exit 0, archive contains exactly `database.sql` (seeded rows present)
  and `uploads.tar` (both seeded files at correct paths). Real `decision-assistant-api`/`-web`
  image IDs/timestamps and real project containers confirmed unchanged before/after; isolated
  project torn down. Script functionality: pass, high confidence. SEPARATE FINDING: tasks.md:264
  still shows T035 as `- [ ]` unmarked despite complete/verified work — inconsistent with this
  loop's pattern of marking `[X]` in the same iteration (T011/T012/T016-T018 precedent); small
  maker-fixable gap for next iteration, does not change D1 (stays correctly `pending` regardless —
  T036/T037 and the rest of tasks.md remain outstanding).) Earlier: maker, iteration 34: added
  `scripts/backup.sh` (T035), targets D1 — see iterations.md Iteration 34. Earlier: checker,
  iteration 33, see V58: D4 independently confirmed
  satisfied on `improvement` at `3e2f32f` directly, no worktree needed (maker's iteration made no
  code change). Ran `docker compose -p d4checkiter33 config`: `api`/`web` have no source
  bind-mounts, `api`/`web` ports resolve `host_ip: 127.0.0.1`, `db` publishes no ports. Separately
  ran with `--profile ollama` (profile-gated, doesn't render by default) and confirmed `ollama`
  also resolves `127.0.0.1`. Checked `.env` first for a local override that could mask the
  result — none found. D4 promoted to `checker-pass`. Isolated project torn down after.) Earlier:
  maker, iteration 33: verified D4 already satisfied on `improvement`
  as-is — no code change made, see iterations.md Iteration 33.) Earlier: checker, iteration 32,
  see V56/V57: DB21 independently confirmed
  fixed by running the LITERAL bare `make test-web`/`make test-api` commands myself (not an
  isolated-project workaround) from worktree `loop-iter-31` at `7eb13f6` — both exit 0
  (`38 passed`/`368 passed, 4 deselected`), both built/ran under the isolated `decision-assistant-test`
  project per the fix, and `docker images` confirmed the real `decision-assistant-api:latest`/
  `decision-assistant-web:latest` tags were untouched before and after (unchanged timestamps/IDs).
  D3 promoted to `checker-pass` for the first time via the literal documented command, not an
  isolation workaround. DB21 marked resolved; DB18's row updated to fully resolved (its
  "resolved-in-isolation" caveat is now closed since the underlying safety gap DB21 covered is
  fixed). Still unmerged, worktree `loop-iter-31` (branch continues to carry both iteration 31 and
  32's commits). This check initially hit a Bash auto-mode permission denial ("Modify Shared
  Resources") on both a bare and an isolated-`-p` docker/make invocation; user granted the
  permission via `/permissions` and the live run then proceeded normally — no lasting debt from
  this, it was a one-time session-local gate, not a code or process issue. Earlier: maker, iteration
  32: fixed DB21, targets D3 — see iterations.md Iteration 32. Earlier:
  checker, iteration 31, see V54/V55: DB18's fix mechanism confirmed
  correct in isolation (`38 passed`, D4 default-target unaffected, minimal 3-line diff matches
  claim exactly) — still unmerged, worktree `loop-iter-31` at `3a5c6af`. FAIL on D3 itself: the
  literal documented `make test-web` (no `-p` override, `compose.yaml` pins `name:
  decision-assistant`) silently overwrites the real deployed `decision-assistant-web:latest` image
  tag with the dev/`build`-stage image instead of `runtime` — confirmed by inspecting `web`'s
  missing `image:` key and the real image's pre-session timestamp; deliberately did not run the
  literal command to avoid causing this for real. `--no-deps` (this iteration's other change)
  prevents the deeper api/db-touching incident class from V52 but not this image-tag overwrite,
  which happens in the `build` step. Same latent bug found in `test-api` (no `-p` either) — new
  high-severity debt DB21 opened covering both targets; this also means D2's existing
  `checker-pass` (V34) and D3 here are both true only when run in isolation, not as literally
  documented. D3 set to `checker-fail`, routes back to the maker to add project isolation to both
  Makefile test targets. Earlier: maker, iteration 31: fixed DB18, targets D3 — see iterations.md
  Iteration 31. Not merged into `improvement` yet by this checker (checker never edits
  implementation). Earlier:
  checker, iteration 30, see V49-V53: T016 and T017 independently
  confirmed correct (full API suite `368 passed, 4 deselected, 0 failed`; web suite, built via
  `web/Dockerfile`'s `build` stage directly since DB18 blocks the compose path, `38 passed (11
  files), 0 failed`). DB18 (`make test-web` broken) independently reproduced live — same failure
  the maker described, D3 correctly stays `pending`. The disclosed isolation incident's
  containment claim is corroborated (image timestamps predate the incident, all three real
  containers correctly left stopped, all four named volumes untouched) though not from a fully
  independent DB-content check (checker had no `.env`/DB credentials to connect directly) — see
  V52. NEW FINDING (V53, fail): `docs/install.md`'s "First run" section, added by this iteration
  outside T018's literal scope, states the app "generates its own local secrets and prompts you to
  set an admin password" — this describes the not-yet-built US5 flow (D9 still `pending`) as
  already-current behavior; `main.py` actually requires `AUTH_BOOTSTRAP_*`/`AUTH_JWT_SECRET` to
  already be set and crashes with an undocumented `RuntimeError` otherwise. Opened debt DB19
  (doc correction needed) and DB20 (found incidentally: the entire `specs/002-production-readiness/`
  tree, including this loop's own state files, is untracked in git — no worktree used by this loop
  has ever actually included it, so "isolated worktree" tasks.md edits were always against the live
  main-tree copy; needs a human decision on committing it). No done-criterion status changed
  beyond what V49-51 already support (D1 stays `pending`, D3 stays `pending`). Earlier: maker,
  iteration 30: completed Phase 3 (US1) T016/T017/T018 — targets
  D1. Opened debt DB18 (`make test-web` broken, pre-existing since T002). Flagging for
  checker/human attention: an isolation incident occurred during verification (unscoped `docker
  compose` command briefly touched the shared default project) — contained with no data/image
  impact per the maker's own investigation, described in full in iterations.md Iteration 30. Earlier:
  checker, iteration 29, see V48: independently confirmed both of
  V46's T014 regressions are fixed — `alembic/env.py`'s `disable_existing_loggers=False` and
  `migrations.py`'s cwd-relative `_ALEMBIC_INI` path. Live-reproduced in a separate isolated
  worktree/project: full suite `366 passed, 4 deselected, 0 failed`; default production image
  booted against a fresh DB shows the migration chain to `0012_production_readiness` (20 tables
  confirmed via `psql`) followed by the previously-silenced `Application startup complete`/
  `Uvicorn running on`/access-log lines, all now present. T014 correctly stays unchecked in
  tasks.md (DB16's backup precursor still unimplemented). No done-criterion status changed — D1
  remains `pending` (T001-T072 far from all complete); this check only closes out V46's
  regression-fix verification. Earlier: maker, iteration 29: fixed checker V46's two T014
  regressions
  (uvicorn logger silencing, non-editable-install path fragility), added `test_migrations.py`,
  live-verified against a fresh DB with the actual production image — see iterations.md
  Iteration 29. Targets D1 (T014). Earlier: checker,
  iteration 28, see V44-V47: T012, T013 and T015 pass. T014's auto-migration works on a fresh DB (0001 to 0012 on boot) but FAILED: alembic `fileConfig` disables the `uvicorn.error` and `uvicorn.access` loggers in the live server, and the `alembic.ini` path works only via compose's PYTHONPATH. New low debt DB17 (T013 interpretation, missing unit tests). D1 stays pending. Earlier: maker, iteration 28: completed Phase 2's remaining tasks T012/T013/T015
  and partial T014 (see iterations.md Iteration 28 and debt DB16) — targets D1. Not yet
  independently checker-verified. Earlier: human user accepted DB5 with residual risk
  (query-parameter and scheme-less passwords can still print through `make config`); DB5 closed, no
  further maker work. Earlier: checker, iteration 27, see V43: the DB5 userinfo leak class is closed
  and the fixture test is verified, but a password as a URL query parameter (`?password=`) still
  leaks through `make config`, so DB5 stays open. No done-criterion status changed. Earlier: maker,
  iteration 27: re-fixed DB5 again per checker V42's leak-safety
  guidance (reverted to a plain greedy `:\/\/.*@` match, accepting over-redaction of a rare
  non-secret path-`@` shape) and added a checked-in fixture regression test — see iterations.md
  Iteration 27. Not yet independently checker-verified. Earlier: checker, iteration 26, see V42: the
  DB5 re-fix FAILED. A password containing `/` in a URL with no path still leaks through
  `make config`, so DB5 stays open. No done-criterion status changed. Earlier: maker, iteration 26:
  re-fixed DB5 again per checker V41's regression
  finding (password containing `/` or a space was left unredacted) — see iterations.md Iteration 26.
  Not yet independently checker-verified. Earlier: checker, iteration 25, see V41: the DB5 re-fix
  FAILED. The V40 cases are fixed, but it regressed on passwords containing `/` or a space, which
  now leak through `make config`, so DB5 stays open. No done-criterion status changed. Earlier:
  maker, iteration 25: re-fixed DB5 again per checker V40's findings —
  see iterations.md Iteration 25. Not yet independently checker-verified. Earlier: checker,
  iteration 24, see V40: the DB5 re-fix FAILED the adversarial check. The V38 cases are fixed, but an empty-username URL and a URL username containing `@` still leak through `make config`, so DB5 stays open. No done-criterion status changed. Earlier: checker, iterations 20-23, see V34-V39: D2 marked checker-pass after live `make test-api` exit 0; DB11/DB6 fixes verified, marked resolved; DB14 moot confirmed; DB5 fix FAILED adversarial check (multi-line secret and raw `@` URL password leak through `make config`), stays open; DB13 extraction verified verbatim but still partial, stays open; new low debt DB15 (AGENTS.md:27 test command broken since DB10/DB11). Earlier history: checker: D5 marked checker-pass after live verification, see V12;
  independently checked T008/T009/T010 (iterations 14-16, see V15-V22) — all three model/schema
  changes live-verified correct against migration 0012's real DB schema and their Pydantic
  response schemas, no regression found in D5 or D2. D2 remains correctly `pending`: live
  `make test-api` run shows 7 failed/20 errors, all pre-existing DB11-class failures unrelated to
  T008-T010. New debt DB12 opened (models.py over the 500-line AGENTS.md cap, grown further by
  T009/T010 without a split or documented exception, unlike T008 which correctly avoided it);
  independently checked Iteration 13's DB10 fix, see V23 — `compose.yaml`'s `api.build.target`
  and `Makefile`'s `test-api` override live-verified correct in an isolated `checker-db10`
  project (lean default has no pytest, `API_BUILD_TARGET=test` override has pytest, full
  `make test-api` run end-to-end with zero new regressions vs. V21's baseline, normal
  install/start path unaffected); DB10 marked resolved; independently checked Iteration 17's DB7
  fix, see V24/V25 — live-reproduced V10's exact original failure scenario in isolated project
  `checker-i17`: restore against an already-populated/conflicting DB now exits 0 with the
  conflicting row genuinely gone (not a silent no-op), malformed-SQL restore now fails loudly
  (exit 2) with prior data intact; DB7 marked resolved. Independently checked Iteration 18's DB12
  fix, see V26/V27/V28 — every split file confirmed under 500 lines (models.py now 22 lines),
  zero stale imports of moved classes found repo-wide, live import/app-boot/alembic/full-pytest
  run in isolated project `checker-i18` matches the pre-split 337-passed/7-failed/20-errors
  baseline exactly; DB12 marked resolved. New debt DB13 opened (found incidentally: 
  `evaluation/service.py` is 1265 lines, over the 500-line cap, pre-existing and unrelated to
  Iteration 18's split). D2 remains correctly `pending` (same pre-existing DB11-class failures,
  no new regressions from iterations 17 or 18). No done-criterion status changed this check beyond
  D5 (already checker-pass); D1 still far from complete (T011-T072 outstanding).
  2026-09-25: independently checked Iteration 19's T011 fix, see V29-V33 — confirmed
  `recover_stale_jobs` was genuinely dead code before removal (grepped pre-commit tree for
  callers/tests, zero found); confirmed maker's signature deviation (`model`/`interrupted_error_code`
  kwargs vs tasks.md's literal `max_attempts`-only signature) is a defensible reading, since T011's
  own text requires reuse by both ingestion (T019/T021) and evaluation (T023) recovery; live-verified
  `recover_and_requeue` in isolated `checker-i19` project including adversarial edge cases
  (`max_attempts=0` fails immediately, boundary `attempt_count == max_attempts` fails not requeues,
  zero running rows is a clean no-op, function only flushes not commits — caller must commit); full
  pytest run `7 failed, 337 passed, 4 deselected, 20 errors` byte-for-byte matches iteration 18's
  baseline, zero regression. New low-severity debt DB14 opened (the "DB11-class deselect" pytest
  flags have never been externalized verbatim across iterations 15/16/18/19 — reproducibility gap,
  not a correctness issue). T011 confirmed correct; D1 still far from complete (T012-T072
  outstanding).)
