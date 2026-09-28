import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.backup import create_pre_migration_backup
from decision_assistant.auth.router import router as authentication_router
from decision_assistant.auth.router import setup_router
from decision_assistant.answering.router import router as answering_router
from decision_assistant.config import Settings, get_settings, validate_startup_config
from decision_assistant.db import create_engine, create_session_factory, get_session
from decision_assistant.decisions.router import router as decisions_router
from decision_assistant.diagnostics.logging import configure_logging
from decision_assistant.diagnostics.router import router as diagnostics_router
from decision_assistant.documents.router import LocalIngestionDispatcher
from decision_assistant.documents.router import router as documents_router
from decision_assistant.documents.storage import LocalFileStorage
from decision_assistant.errors import ApplicationError, ErrorResponse
from decision_assistant.evaluation.models import EvaluationRun
from decision_assistant.evaluation.router import EvaluationBackgroundRunner
from decision_assistant.evaluation.router import router as evaluation_router
from decision_assistant.ingestion.models import DocumentVersion, IngestionJob
from decision_assistant.ingestion.profiles import resolve_corpus_profile
from decision_assistant.jobs.recovery import recover_and_requeue
from decision_assistant.migrations import is_upgrade_pending, upgrade_to_head
from decision_assistant.retrieval.router import router as retrieval_router
from decision_assistant.providers.base import ProviderConfigurationInvalid
from decision_assistant.providers.factory import (
    CachedProviderBundleFactory,
    configured_embedding_profile,
    validate_selected_provider_configuration,
)
from decision_assistant.timelines.router import router as timelines_router
from decision_assistant.version import get_app_version
from decision_assistant.workspace.embedding_profile import (
    CorpusResetRequired,
    get_corpus_state,
    require_current_corpus_profiles,
)
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.provider_config import (
    apply_stored_provider_config,
    load_stored_provider_config,
)
from decision_assistant.workspace.rebuild.dispatch import (
    dispatch_corpus_rebuild,
    mark_interrupted_rebuilds,
)
from decision_assistant.workspace.router import router as workspaces_router

RequestHandler = Callable[[Request], Awaitable[Response]]

# quickstart.md Section 3 tells the operator to confirm recovery from the logs
# (`docker compose logs api | grep -i "recover\|requeue"`). `configure_logging`
# (T056) also writes a rotating file log, but startup recovery is emitted through
# uvicorn's logger deliberately: `docker compose logs` reads the container's
# stdout/stderr, and uvicorn gives `uvicorn.error` its own handler, so a record
# sent here reaches both the console and the file.
_startup_logger = logging.getLogger("uvicorn.error")


class ServiceNotReady(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="service_not_ready",
            message="Service is not ready",
            status_code=503,
            retryable=True,
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: Any | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        request_id=_request_id(request),
        retryable=retryable,
        details=details,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    # T056 (US7/FR-017): rotating, secret-scrubbed file logging. Done here rather
    # than inside `lifespan` so that a startup failure in `lifespan` is itself
    # written to the log file, not only to the container's stderr.
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        bootstrap_engine = None
        try:
            # T045: fail fast on a missing AUTH_JWT_SECRET or a placeholder
            # DATABASE_URL before touching the DB at all (DB8) — a
            # ConfigurationError here aborts startup, so migrations/backups
            # never run against a shared-default credential.
            validate_startup_config(resolved_settings)
            # T014's pre-migration backup (FR-005). Distinct from `make backup`/
            # scripts/backup.sh (FR-008, DB22): that script shells out to `docker compose
            # exec`, a HOST-side tool this in-container lifespan hook can't reach, so
            # create_pre_migration_backup does its own pg_dump/tar directly against the
            # mounted uploads volume and DATABASE_URL (human-approved dependency addition,
            # see loop debt DB22, resolved iteration 37). Gated on is_upgrade_pending: a
            # backup taken on every no-op restart rotates out before a real migration ever
            # needs it (checker V63). Must run, and must succeed, before the schema upgrade
            # below when pending — a failed backup should block migration, not be silently
            # skipped.
            if await asyncio.to_thread(is_upgrade_pending, resolved_settings):
                await asyncio.to_thread(create_pre_migration_backup, resolved_settings)
            await asyncio.to_thread(upgrade_to_head)
            bootstrap_engine = create_engine(resolved_settings)
            bootstrap_session_factory = create_session_factory(bootstrap_engine)
            # T050: a provider switch is stored in `app_settings` and applied over the environment
            # defaults here, before anything resolves a provider or a corpus profile, so the whole
            # process agrees on one effective configuration after a restart.
            async with bootstrap_session_factory() as session:
                stored_provider_config = await load_stored_provider_config(session)
                if stored_provider_config is not None:
                    apply_stored_provider_config(resolved_settings, stored_provider_config)
            # T042 (US5): no user is created here any more. The old env bootstrap used
            # AUTH_BOOTSTRAP_USERNAME/AUTH_BOOTSTRAP_PASSWORD to define "the" user at startup, which
            # meant the app chose a credential from two more shared-default `.env` values. A fresh
            # install now starts with no user and GET /api/v1/setup/status reports it; the operator
            # sets the password through POST /api/v1/setup/password.
            # T021: a job left `running` by a crash/restart is requeued (or marked
            # terminal `failed` past max_ingestion_attempts) so it never sits stuck
            # in `processing` forever (DB19/D1, quickstart.md Section 3). Resolve
            # each requeued job's source file before commit, so re-dispatch below
            # uses stable data even if a later step fails.
            storage = LocalFileStorage(resolved_settings.upload_directory)
            redispatches: list[tuple[Any, Any, str, Any]] = []
            async with bootstrap_session_factory() as session:
                # DB27: also sweep `pending` — a job whose fire-and-forget
                # background dispatch (router.py's `upload_documents`) never
                # started before a crash/restart is left `pending` forever
                # otherwise, since it never reached `running` for the
                # default-only sweep to find.
                outcome = await recover_and_requeue(
                    session,
                    model=IngestionJob,
                    max_attempts=resolved_settings.max_ingestion_attempts,
                    interrupted_error_code="ingestion_interrupted",
                    statuses=("running", "pending"),
                    finished_at_field="finished_at",
                )
                for job in outcome.requeued:
                    version = (
                        await session.get(DocumentVersion, job.document_version_id)
                        if job.document_version_id is not None
                        else None
                    )
                    if version is None:
                        continue
                    redispatches.append(
                        (
                            job.document_id,
                            job.id,
                            job.request_id,
                            storage.local_path(version.storage_path),
                        )
                    )
                await session.commit()
                if outcome.requeued or outcome.failed:
                    _startup_logger.info(
                        "startup recovery: requeued %d ingestion job(s) "
                        "(%d dispatched), marked %d failed",
                        len(outcome.requeued),
                        len(redispatches),
                        len(outcome.failed),
                    )
            # DB27: `asyncio.create_task` returns the event loop's only
            # strong reference; without holding one ourselves the task can be
            # garbage-collected mid-run. `application.state` outlives this
            # function, so tasks stored there survive until they finish, and
            # the done-callback prunes each one out once it has (successful
            # or not — failures are already recorded via `_record_dispatch_failure`
            # inside `dispatch`).
            application.state.startup_redispatch_tasks = set()
            if redispatches:
                dispatcher = LocalIngestionDispatcher(
                    resolved_settings, application.state.provider_bundle_factory
                )
                for document_id, job_id, request_id, source_path in redispatches:
                    task = asyncio.create_task(
                        dispatcher.dispatch(
                            document_id=document_id,
                            job_id=job_id,
                            source_path=source_path,
                            request_id=request_id,
                        )
                    )
                    application.state.startup_redispatch_tasks.add(task)
                    task.add_done_callback(
                        application.state.startup_redispatch_tasks.discard
                    )

            # T023: same recovery pattern as the IngestionJob sweep above, for
            # EvaluationRun rows left `running`/`pending` by a crash/restart.
            # `EvaluationBackgroundRunner.dispatch(run_id)` (documents/router.py's
            # `LocalIngestionDispatcher` equivalent) re-resolves everything it
            # needs from `run_id` alone via `EvaluationService.execute_run`,
            # which already accepts both `pending` and `running` — no extra
            # per-row lookup (like ingestion's `DocumentVersion.storage_path`)
            # is needed before redispatch. `error_field="failure"`: EvaluationRun
            # names its failure column `failure`, not `error` (see
            # jobs/recovery.py's `recover_and_requeue` docstring).
            async with bootstrap_session_factory() as session:
                evaluation_outcome = await recover_and_requeue(
                    session,
                    model=EvaluationRun,
                    max_attempts=resolved_settings.max_evaluation_attempts,
                    interrupted_error_code="evaluation_interrupted",
                    statuses=("running", "pending"),
                    error_field="failure",
                    finished_at_field="completed_at",
                )
                requeued_run_ids = [run.id for run in evaluation_outcome.requeued]
                await session.commit()
                if evaluation_outcome.requeued or evaluation_outcome.failed:
                    _startup_logger.info(
                        "startup recovery: requeued %d evaluation run(s) "
                        "(%d dispatched), marked %d failed",
                        len(evaluation_outcome.requeued),
                        len(requeued_run_ids),
                        len(evaluation_outcome.failed),
                    )
            if requeued_run_ids:
                runner = EvaluationBackgroundRunner(
                    resolved_settings, application.state.provider_bundle_factory
                )
                for run_id in requeued_run_ids:
                    task = asyncio.create_task(runner.dispatch(run_id))
                    application.state.startup_redispatch_tasks.add(task)
                    task.add_done_callback(
                        application.state.startup_redispatch_tasks.discard
                    )

            # T029: a workspace whose stored corpus contract no longer matches
            # the configured embedding/chunking profile (`corpus_reset_required`,
            # computed, not a stored flag — `get_corpus_state`) needs a rebuild
            # before it is usable again (DB40's `run_corpus_rebuild`, US3/T028
            # +T031). Detect every such workspace up front in one session, then
            # dispatch each rebuild as its own tracked background task (same
            # shape as the ingestion/evaluation redispatch above) — a rebuild
            # can re-parse and re-embed every document in the workspace, too
            # slow to run inline before `yield`.
            #
            # DB41: the rebuild's row is committed before its work starts (so
            # progress is visible while it runs), which means a crash mid-run
            # leaves a `pending`/`running` row that the single-active-rebuild
            # unique index will never let a later rebuild past. Sweep those
            # first, before the reset-required scan below tries to insert one:
            # a workspace that still needs rebuilding is re-dispatched by that
            # same scan, so an interrupted rebuild recovers on its own.
            async with bootstrap_session_factory() as session:
                interrupted = await mark_interrupted_rebuilds(session)
                await session.commit()
                if interrupted:
                    _startup_logger.info(
                        "startup recovery: marked %d interrupted corpus "
                        "rebuild(s) failed",
                        len(interrupted),
                    )
            async with bootstrap_session_factory() as session:
                configured_embedding = configured_embedding_profile(resolved_settings)
                configured_chunking = resolve_corpus_profile(
                    resolved_settings.chunking_profile_preset,
                    resolved_settings.retrieval_unit_strategy,
                )
                reset_required_workspace_ids: list[Any] = []
                for workspace_id in await session.scalars(select(Workspace.id)):
                    state = await get_corpus_state(
                        session,
                        workspace_id,
                        configured_embedding,
                        configured_chunking,
                    )
                    if state.corpus_reset_required:
                        reset_required_workspace_ids.append(workspace_id)
            if reset_required_workspace_ids:
                _startup_logger.info(
                    "startup: %d workspace(s) need a corpus rebuild",
                    len(reset_required_workspace_ids),
                )
                for workspace_id in reset_required_workspace_ids:
                    task = asyncio.create_task(
                        dispatch_corpus_rebuild(
                            bootstrap_session_factory,
                            workspace_id=workspace_id,
                            reason="corpus_reset_required",
                            settings=resolved_settings,
                            providers=application.state.provider_bundle_factory(),
                            request_id=str(uuid4()),
                            logger=_startup_logger,
                        )
                    )
                    application.state.startup_redispatch_tasks.add(task)
                    task.add_done_callback(
                        application.state.startup_redispatch_tasks.discard
                    )
            yield
        finally:
            if bootstrap_engine is not None:
                await bootstrap_engine.dispose()
            await application.state.provider_bundle_factory.aclose()

    app = FastAPI(title="Decision Assistant API", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.provider_bundle_factory = CachedProviderBundleFactory(
        resolved_settings
    )
    app.include_router(authentication_router)
    app.include_router(setup_router)
    app.include_router(answering_router)
    app.include_router(decisions_router)
    app.include_router(diagnostics_router)
    app.include_router(documents_router)
    app.include_router(evaluation_router)
    app.include_router(retrieval_router)
    app.include_router(timelines_router)
    app.include_router(workspaces_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: RequestHandler,
    ) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = "Not found" if exc.status_code == 404 else str(exc.detail)
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        _: Exception,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Internal server error",
            retryable=True,
        )

    @app.get("/health")
    async def health(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str]:
        try:
            await session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise ServiceNotReady() from None
        return {"status": "ok", "version": get_app_version()}

    @app.get("/ready")
    async def ready(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str]:
        try:
            validate_selected_provider_configuration(resolved_settings)
            await require_current_corpus_profiles(
                session,
                configured_embedding_profile(resolved_settings),
                resolve_corpus_profile(
                    resolved_settings.chunking_profile_preset,
                    resolved_settings.retrieval_unit_strategy,
                ),
            )
        except (
            ProviderConfigurationInvalid,
            CorpusResetRequired,
            SQLAlchemyError,
        ):
            raise ServiceNotReady() from None
        return {"status": "ready"}

    return app


app = create_app()
