import asyncio
import logging
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from decision_assistant.config import Settings, get_settings
from decision_assistant.ingestion.models import Document, DocumentVersion, IngestionJob
from decision_assistant.main import create_app
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import FakeEmbeddingProvider, FakeGenerationProvider
from decision_assistant.workspace.models import Workspace

# The test DB is truncated once per pytest session, not per test
# (conftest.py's `_isolated_test_database`), and `EmbeddingCache` dedup is
# workspace-scoped (`ingestion/service.py`'s `_resolve_embedding_cache`), so
# every real ingestion this file runs leaves rows another file's test may
# count globally (e.g. test_ingestion_service.py's unscoped
# `SELECT count(*) FROM embedding_cache`). `workspaces.id` cascades
# (`ON DELETE CASCADE`) through documents/versions/jobs/passages/cache, so
# deleting the workspace after each test restores a clean slate.
@asynccontextmanager
async def _cleanup_workspace(db_session: AsyncSession, workspace_id: object):
    try:
        yield
    finally:
        workspace = await db_session.get(Workspace, workspace_id)
        if workspace is not None:
            await db_session.delete(workspace)
            await db_session.commit()

# Frontmatter supplies every DocumentMetadata field, so MetadataExtractor's
# deterministic path is used and no generation call is needed for metadata —
# only the decision extractor calls the fake generation provider. Content is
# deliberately distinct from other fixtures (e.g. test_ingestion_service.py's
# GOOD_CONTENT): the test DB is truncated once per pytest session, not per
# test (conftest.py), so identical passage text elsewhere would inflate an
# unscoped `SELECT count(*) FROM embedding_cache` in another file's test.
GOOD_CONTENT = """---
title: Restart Recovery Drill
date: 2026-07-20
participants: [Priya, Tomas]
source_type: incident-review
project: Atlas
---

# Ingestion Restart Recovery

The startup sweep must requeue interrupted ingestion jobs without manual resubmission.
"""


class FakeProviderBundleFactory:
    """Replaces the real `CachedProviderBundleFactory` so the startup
    sweep's real redispatch path (`LocalIngestionDispatcher` ->
    `IngestionService.ingest`) runs against deterministic fakes instead of
    a live model provider."""

    def __init__(self) -> None:
        self.embedding = FakeEmbeddingProvider(dimension=768)
        self.generation = FakeGenerationProvider([{"decisions": []}] * 10)

    def __call__(self) -> ProviderBundle:
        return ProviderBundle(embedding=self.embedding, generation=self.generation)

    async def aclose(self) -> None:
        return None


@asynccontextmanager
async def _loop_local_dispatch_session_factory(monkeypatch: pytest.MonkeyPatch):
    """`decision_assistant.documents.router` binds `session_factory` from
    `decision_assistant.db` at import time, and that module-level engine is a
    process-wide singleton created once against whichever event loop is
    running when it first opens a connection. Each `pytest.mark.asyncio` test
    runs on its own fresh event loop by default, so a second test reusing
    that same asyncpg-backed engine fails with "Future ... attached to a
    different loop". Give the dispatch path (used here, unlike other tests,
    because T020/DB27 need the *real* redispatch to run) its own engine bound
    to this test's loop instead of the shared singleton."""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import decision_assistant.documents.router as router_module

    monkeypatch.setattr(router_module, "session_factory", factory)
    try:
        yield
    finally:
        await engine.dispose()


async def _seed_job(
    db_session: AsyncSession,
    tmp_path: object,
    *,
    workspace_name: str,
    source_filename: str,
    checksum: str,
    request_id: str,
    status: str,
    stage: str,
    attempt_count: int = 0,
) -> tuple[IngestionJob, object]:
    workspace = Workspace(name=workspace_name, embedding_profile=None)
    db_session.add(workspace)
    await db_session.flush()
    document = Document(
        workspace_id=workspace.id,
        display_name=source_filename,
        media_type="text/markdown",
    )
    db_session.add(document)
    await db_session.flush()
    source_file = tmp_path / source_filename
    source_file.write_text(GOOD_CONTENT)
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        checksum=checksum,
        storage_path=source_file.name,
        state="staging",
    )
    db_session.add(version)
    await db_session.flush()
    job = IngestionJob(
        document_id=document.id,
        document_version_id=version.id,
        stage=stage,
        status=status,
        progress=0,
        attempt_count=attempt_count,
        request_id=request_id,
    )
    db_session.add(job)
    await db_session.flush()
    await db_session.commit()  # visible to the lifespan's own DB connection below
    return job, workspace.id


@pytest.mark.asyncio
async def test_startup_sweep_drives_interrupted_running_job_to_terminal_state(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    # Simulates an API restart: an IngestionJob left `running` by a killed
    # process (no crash-recovery event fires `finished_at`/`status` change).
    job, workspace_id = await _seed_job(
        db_session,
        tmp_path,
        workspace_name="restart-recovery",
        source_filename="restart-recovery.md",
        checksum="b" * 64,
        request_id="restart-recovery",
        status="running",
        stage="parsing",
    )

    async with _cleanup_workspace(db_session, workspace_id):
        import decision_assistant.main as main_module

        monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

        app = create_app(
            Settings(
                auth_jwt_secret="test-signing-secret-for-restart-recovery",
                upload_directory=tmp_path,
            )
        )
        app.state.provider_bundle_factory = FakeProviderBundleFactory()

        async with _loop_local_dispatch_session_factory(monkeypatch):
            async with app.router.lifespan_context(app):
                tasks = app.state.startup_redispatch_tasks
                assert len(tasks) == 1
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

        await db_session.refresh(job)
        # T020: the startup sweep (T021) must drive the job to a real
        # terminal state, not merely flip it back to `pending` and record a
        # stub call — `pending` is not terminal and a test that stops there
        # proves nothing about whether the redispatched ingestion actually
        # completes.
        assert job.status == "completed"
        assert job.attempt_count == 1
        version = await db_session.get(DocumentVersion, job.document_version_id)
        assert version is not None
        assert version.state == "active"


@pytest.mark.asyncio
async def test_startup_sweep_logs_recovery_counts(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    # D6: quickstart.md Section 3 verifies recovery with
    # `docker compose logs api | grep -i "recover|requeue"`, so the sweep has to
    # emit a line that grep matches. It goes to `uvicorn.error` because the app
    # still configures no logging of its own (US7/T056 does that), and a
    # module-level logger would therefore emit nothing at INFO.
    job, workspace_id = await _seed_job(
        db_session,
        tmp_path,
        workspace_name="restart-recovery-logging",
        source_filename="restart-recovery-logging.md",
        checksum="d" * 64,
        request_id="restart-recovery-logging",
        status="running",
        stage="parsing",
    )

    async with _cleanup_workspace(db_session, workspace_id):
        import decision_assistant.main as main_module

        monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

        app = create_app(
            Settings(
                auth_jwt_secret="test-signing-secret-for-restart-recovery-logging",
                upload_directory=tmp_path,
            )
        )
        app.state.provider_bundle_factory = FakeProviderBundleFactory()

        messages: list[str] = []

        class _Collect(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                messages.append(record.getMessage())

        # Watch `uvicorn.error` itself. Uvicorn gives that logger its own
        # handler and `propagate = False`, so the record never reaches the root
        # logger and `caplog` sees nothing — the line shows up only under
        # "Captured stderr" unless a handler is attached right here.
        target = logging.getLogger("uvicorn.error")
        handler = _Collect()
        previous_level = target.level
        target.setLevel(logging.INFO)
        target.addHandler(handler)
        try:
            async with _loop_local_dispatch_session_factory(monkeypatch):
                async with app.router.lifespan_context(app):
                    await asyncio.wait_for(
                        asyncio.gather(*app.state.startup_redispatch_tasks),
                        timeout=5,
                    )
        finally:
            target.removeHandler(handler)
            target.setLevel(previous_level)

        assert (
            "startup recovery: requeued 1 ingestion job(s) (1 dispatched), "
            "marked 0 failed"
        ) in messages
        # The sweep still did its real work, not just the logging.
        await db_session.refresh(job)
        assert job.status == "completed"
        assert job.attempt_count == 1


@pytest.mark.asyncio
async def test_startup_sweep_also_recovers_job_left_pending_before_dispatch_started(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    # DB27: a job crashed before its fire-and-forget background dispatch
    # ever flipped it to `running` (e.g. the process died between the
    # upload request's commit and `IngestionService.ingest`'s first write).
    # The old sweep only scanned `status == "running"` and left such jobs
    # stuck in `pending` forever, since a normal (non-crashed) `pending` row
    # is only ever momentary. This is also the corpus upload path (T022).
    job, workspace_id = await _seed_job(
        db_session,
        tmp_path,
        workspace_name="restart-recovery-pending",
        source_filename="interrupted-pending.md",
        checksum="c" * 64,
        request_id="restart-recovery-pending",
        status="pending",
        stage="queued",
    )

    async with _cleanup_workspace(db_session, workspace_id):
        import decision_assistant.main as main_module

        monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

        app = create_app(
            Settings(
                auth_jwt_secret="test-signing-secret-for-restart-recovery-pending",
                upload_directory=tmp_path,
            )
        )
        app.state.provider_bundle_factory = FakeProviderBundleFactory()

        async with _loop_local_dispatch_session_factory(monkeypatch):
            async with app.router.lifespan_context(app):
                tasks = app.state.startup_redispatch_tasks
                assert len(tasks) == 1
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

        await db_session.refresh(job)
        assert job.status == "completed"
        assert job.attempt_count == 1
        version = await db_session.get(DocumentVersion, job.document_version_id)
        assert version is not None
        assert version.state == "active"


@pytest.mark.asyncio
async def test_startup_sweep_marks_job_at_max_attempts_failed_with_reason_and_timestamp(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    # DB28 (parity for ingestion): `main.py`'s call site must pass
    # `finished_at_field="finished_at"` — dropping it survives every other
    # test in this file, since those only exercise the `requeued`
    # (under-`max_attempts`) path, never the terminal `failed` path.
    job, workspace_id = await _seed_job(
        db_session,
        tmp_path,
        workspace_name="restart-recovery-max-attempts",
        source_filename="restart-recovery-max-attempts.md",
        checksum="d" * 64,
        request_id="restart-recovery-max-attempts",
        status="running",
        stage="parsing",
        attempt_count=3,  # == default max_ingestion_attempts
    )

    async with _cleanup_workspace(db_session, workspace_id):
        import decision_assistant.main as main_module

        monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

        app = create_app(
            Settings(
                auth_jwt_secret="test-signing-secret-for-max-attempts",
                upload_directory=tmp_path,
            )
        )
        app.state.provider_bundle_factory = FakeProviderBundleFactory()

        async with app.router.lifespan_context(app):
            # A job at max attempts is marked terminal `failed` directly, no
            # redispatch — nothing to await here.
            assert len(app.state.startup_redispatch_tasks) == 0

        await db_session.refresh(job)
        assert job.status == "failed"
        assert job.attempt_count == 3
        assert job.error == {"code": "ingestion_interrupted"}
        assert job.finished_at is not None
