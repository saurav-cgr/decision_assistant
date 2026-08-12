# Multi-Workspace Project Isolation — Focused Design & Implementation Plan

> **For agentic workers:** REQUIRED: Use `superpowers:subagent-driven-development` (if subagents available) or `superpowers:executing-plans` to implement this plan. Use `@superpowers:test-driven-development` for every behavior change and `@superpowers:verification-before-completion` before claiming a task complete. Steps use checkbox (`- [ ]`) syntax.

**Status:** **APPROVED 2026-08-12.** This is the focused design/specification and implementation plan required by the `## Approved Next Product Direction: Multi-Workspace Project Isolation` section of `2026-08-05-decision-memory-assistant.md`. The P1 boundary gate has been satisfied; implementation may begin.

**Invariant (unchanged from parent plan):** *one workspace represents exactly one project.* A workspace is the isolation boundary for documents, document versions, passages, decisions, evidence, decision relations, revisions, user corrections, timelines, retrieval traces, embedding profile, and evaluation runs.

**Scope note (unchanged):** Authorization is **out of scope**. This is application-level project separation for one local user, **not** security-grade multi-tenancy.

---

## Approved Design Decisions (2026-08-12)

| Boundary decision | Resolution |
| --- | --- |
| API workspace addressing | **Path prefix**: project-data routes move under `/api/v1/workspaces/{workspace_id}/...`. Workspace *management* (CRUD/activate) lives at `/api/v1/workspaces`. |
| Active-workspace persistence | **Server-side**: an active workspace is persisted in the database and returned by the API; the frontend restores it from the server on load. |
| Archive vs delete | **Both**: archive (soft) first; permanent cascade delete is allowed **only** for archived workspaces. |
| Legacy `DocumentVersion.project` | **Retain as-is** (display only). Workspace is the isolation boundary; `project` is not rewritten. |
| Public API versioning | Retain `/api/v1`; project-data routes are re-nested under `/api/v1/workspaces/{id}`. No unversioned aliases, no `/api/v2` (no external clients exist). |

---

## Current State (verified against code, 2026-08-12)

Already workspace-aware (reuse, do not re-implement):
- `Workspace` model (`id`, `name` unique, `embedding_profile` JSONB).
- `Document.workspace_id` FK + index.
- `WorkspaceService.get_or_create()` — currently resolves the **single** first workspace.
- `ingestion/service.py` uses `document.workspace_id` and `acquire_workspace_embedding_lock`.
- `workspace/embedding_migration.py` — workspace-scoped snapshot, predicates, advisory lock, `require_current_embedding_profile`, `EmbeddingReindexRequired`.
- `commands/reindex_embeddings.py` — already accepts `--workspace-id`.
- Retrieval gating is already workspace-scoped via active-passage predicates.

Gaps this plan closes:
1. `RetrievalTrace` has **no** `workspace_id`.
2. `EvaluationQuestion` / `EvaluationRun` / `EvaluationResult` have **no** `workspace_id`.
3. No workspace **management** API (create/list/rename/archive/delete/activate).
4. No **explicit workspace context** on project-data requests — routers rely on `get_or_create()` (single-workspace assumption).
5. No **frontend workspace selector** / active-workspace display.
6. No **isolation tests** proving zero cross-workspace leakage.

---

## Data Model Changes (Alembic migration `0003_workspace_management`)

`Workspace`:
- Add `status: String(20)` with check `('active','archived')`, default `'active'`, not null.
- Add `is_active: Boolean` default `false`, not null, with a **partial unique index** enforcing at most one active workspace:
  `CREATE UNIQUE INDEX uq_workspaces_one_active ON workspaces (is_active) WHERE is_active = true;`
- `name` already `unique`.

New foreign keys (retrofit isolation):
- `RetrievalTrace.workspace_id: UUID` FK → `workspaces.id` (ondelete CASCADE), indexed.
- `EvaluationQuestion.workspace_id: UUID` FK → `workspaces.id` (ondelete CASCADE), indexed.
- `EvaluationRun.workspace_id: UUID` FK → `workspaces.id` (ondelete CASCADE), indexed.

Backfill (backwards-compatible; must not recreate or rewrite source records):
- Set `is_active = true` on the single existing workspace.
- Backfill `workspace_id` on existing `retrieval_traces` and `evaluation_*` rows by joining through their documents where possible; traces/runs not attributable to a document resolve to the (single) existing workspace.
- Set `status = 'active'` on the existing workspace.

No changes to `Document`, `DocumentVersion`, `Passage`, `Decision`, `DecisionEvidence`, `DecisionRelation`, `DecisionRevision`, `IngestionJob` — they remain workspace-scoped transitively via `Document.workspace_id` (documents are the root of every source-derived chain).

---

## API Surface

### Workspace management (new router `workspaces/router.py`)
All under `/api/v1/workspaces`:

- `GET /api/v1/workspaces` → list (id, name, status, is_active, document_count, created_at).
- `POST /api/v1/workspaces` `{name}` → create (unique name; 409 on duplicate); first workspace becomes active.
- `GET /api/v1/workspaces/{id}` → detail.
- `PATCH /api/v1/workspaces/{id}` `{name?}` → rename (name must remain unique).
- `POST /api/v1/workspaces/{id}/activate` → set as the single active workspace (clears others).
- `POST /api/v1/workspaces/{id}/archive` → soft-archive (only if not the active workspace; an active workspace must first be activated elsewhere).
- `DELETE /api/v1/workspaces/{id}` → **only allowed when `status == 'archived'`**; cascade-deletes all workspace data; returns 409 for non-archived, 409 if it is the active workspace.

### Project-data routes (re-nested under explicit workspace context)
Move the existing business routers from `/api/v1/...` to `/api/v1/workspaces/{workspace_id}/...`:

- Documents: `.../documents` (upload, list, detail, retry)
- Questions (answering): `.../questions`
- Decisions: `.../decisions`, `.../decisions/{id}/relations`
- Timelines: `.../timelines`
- Retrieval: `.../retrieval/search` (traces remain addressable by id: `GET /api/v1/workspaces/{id}/retrieval-traces/{trace_id}`)
- Evaluation: `.../evaluation/runs` etc.

**Enforcement pattern:** a `WorkspaceContext` dependency validates the `{workspace_id}` path param, loads the `Workspace`, rejects missing/archived workspaces with the stable error shape, and provides the resolved id + a scoped session to the service. **Every** project-data read/write path must receive and use this dependency — no service may fall back to `get_or_create()`.

`/health`, `/docs`, `/openapi.json`, and the provider `/ready` endpoint remain unversioned and unchanged.

---

## Backend Changes (affected files)

- `models.py` — `Workspace` fields; `workspace_id` on `RetrievalTrace`, `EvaluationQuestion`, `EvaluationRun`.
- `alembic/versions/0003_workspace_management.py` — new migration (above).
- `workspace/service.py` — replace `get_or_create()` with: `create`, `list`, `get`, `rename`, `activate`, `archive`, `delete_archived`, `get_active`, `get_or_create_active`.
- **New** `workspace/router.py` — workspace management endpoints + `WorkspaceContext` dependency.
- `documents/service.py` / `router.py` — accept explicit `workspace_id`; stop calling `get_or_create()`; add `document_count` helper.
- `answering/router.py`, `decisions/router.py`, `timelines/router.py`, `retrieval/router.py`, `evaluation/router.py` — add `{workspace_id}` prefix + `WorkspaceContext`; thread workspace_id into services.
- `retrieval/service.py`, `retrieval/repository.py` — persist `workspace_id` on `RetrievalTrace`; already-scoped predicates retained.
- `evaluation/service.py` — scope questions/runs/results by `workspace_id`.
- `main.py` — include the new workspaces router; keep router order.
- `commands/reindex_embeddings.py` — default `--workspace-id` to the active workspace when omitted.

---

## Frontend Changes

- **New** `web/src/api/workspaces.ts` + client methods (list, create, activate, rename, archive, delete).
- **New** `web/src/components/WorkspaceSelector.tsx` — dropdown in `AppShell`; loads workspaces, shows active workspace, supports create/switch.
- `web/src/api/client.ts` — project-data requests become `/api/v1/workspaces/{activeWorkspaceId}/...`; expose an active-workspace store.
- Active workspace is restored from the server on app load (server-side persistence decision).
- `web/src/app/router.tsx` — browser routes stay unversioned (`/`, `/ask`, `/timeline`, `/decisions/:id`, `/evaluation`); add workspace selection state.
- The `Workspace.tsx` page remains the **document** management screen (rename to clarify if needed); workspace management lives in the selector/header.
- Show active workspace name prominently; disallow/route actions on the active workspace archive/delete paths.

---

## RED Tests (deterministic, no network)

### Backend unit/integration
- `workspace/service` lifecycle: create → list → activate (at most one active) → rename → archive → delete-archived; reject delete of non-archived; reject archive/delete of the active workspace; duplicate name → `409`.
- Retrieval/evaluation persist `workspace_id`; retrieval traces are scoped.
- **Isolation matrix (core acceptance):** seed two workspaces with *identical* filenames and *identical* topics; assert zero leakage across:
  keyword search, semantic search, decision list/detail, relation, revision, correction, timeline, citation/answering, retrieval trace, evaluation question/run/result, and reindex/embedding-profile state.
- Migration test: existing single workspace becomes active; existing source records, decisions, evidence, relations, revisions, corrections, passage ids, offsets, hashes unchanged.
- API namespace test (mirrors Task 8A): project-data paths appear under `/api/v1/workspaces/{id}/...`; old `/api/v1/documents` returns `404`; `/health`, `/docs`, `/openapi.json` unchanged.
- Workspace-scoped advisory lock / embedding-profile gating still holds per workspace (migration of one workspace does not block the other).

### Frontend (Vitest)
- Selector renders workspaces, shows active, switches workspace and re-issues project-data calls with the new id.
- Active workspace restored from server on load.
- Archive/delete controls gated on status + active state.

---

## Verification Commands (run from repo root through Docker)

```bash
# Deterministic suite (no key, no network)
docker compose run --rm api pytest -m 'not live_provider' -v

# Migration against fresh + existing dev DB
docker compose up -d db --wait
docker compose run --rm api alembic upgrade head

# Frontend
docker compose run --rm web npm test -- --run
docker compose run --rm web npm run build

# Compose smoke still green (fake deterministic mode)
SMOKE_PROVIDER_MODE=fake bash scripts/smoke.sh

# Repo hygiene
git diff --check
```

---

## Acceptance Evidence (maps to parent plan's minimum evidence)

1. Create two project workspaces and ingest different documents into each → both visible, distinct.
2. Ask the **same** question in both workspaces → only workspace-local evidence/citations returned (isolation matrix passes).
3. Independent decision timelines and evaluation results per workspace.
4. Reindex/migrate one workspace's embedding profile without blocking or modifying the other (workspace advisory lock + profile state independent).
5. Restart the Compose stack → both workspaces and their data retained; active workspace restored from server.

---

## Commit Sequence (one commit per logical unit)

1. `feat: add workspace lifecycle service and management API` (models + migration + workspace service + router + RED tests)
2. `feat: scope project-data APIs under workspace context` (re-nest routers, thread workspace_id, retrieval/evaluation scoping, API-namespace tests)
3. `feat: add workspace selector and active-workspace state to web` (frontend)
4. `feat: add cross-workspace isolation tests and acceptance` (isolation matrix + migration invariants)

---

## Review Resolutions (approved 2026-08-12)

- **Delete UX:** YES — add a destructive-confirmation dialog on the frontend before permanently deleting an archived workspace.
- **Evaluation corpus:** YES — `evaluation/questions.json` remains a shared template corpus; runs/results are workspace-scoped.
- **Workspace name uniqueness:** YES — enforce **case-insensitively** (use `citext` column type or a functional lower-case unique index).
