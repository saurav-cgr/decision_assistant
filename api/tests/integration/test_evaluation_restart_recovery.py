import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from decision_assistant.config import Settings, get_settings
from decision_assistant.evaluation.models import EvaluationRun
from decision_assistant.main import create_app
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import FakeEmbeddingProvider, FakeGenerationProvider
from decision_assistant.workspace.models import Workspace


class FakeProviderBundleFactory:
    """Same role as test_ingestion_restart_recovery.py's factory of the same
    name: replaces `CachedProviderBundleFactory` so the real redispatch path
    (`EvaluationBackgroundRunner` -> `EvaluationService.execute_run`) runs
    against deterministic fakes instead of a live model provider."""

    def __init__(self) -> None:
        self.embedding = FakeEmbeddingProvider(dimension=768)
        self.generation = FakeGenerationProvider()

    def __call__(self) -> ProviderBundle:
        return ProviderBundle(embedding=self.embedding, generation=self.generation)

    async def aclose(self) -> None:
        return None


@asynccontextmanager
async def _loop_local_evaluation_runner(monkeypatch: pytest.MonkeyPatch):
    """`evaluation/router.py`'s `EvaluationBackgroundRunner.session_maker`
    defaults to `decision_assistant.db.session_factory` — a process-wide
    asyncpg-backed engine singleton bound to whichever event loop first opens
    a connection through it (same issue as
    test_ingestion_restart_recovery.py's `_loop_local_dispatch_session_factory`).
    That default is a class-definition-time binding, so monkeypatching the
    module attribute afterward has no effect; instead, wrap the real class so
    `main.py`'s construction call (`EvaluationBackgroundRunner(settings,
    provider_factory)`, no `session_maker` kwarg) picks up a fresh engine
    bound to this test's own event loop."""
    engine = create_async_engine(get_settings().database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    import decision_assistant.main as main_module

    real_runner_cls = main_module.EvaluationBackgroundRunner

    def _bound_runner(settings, provider_factory):
        return real_runner_cls(settings, provider_factory, session_maker=session_maker)

    monkeypatch.setattr(main_module, "EvaluationBackgroundRunner", _bound_runner)
    try:
        yield
    finally:
        await engine.dispose()


async def _seed_run(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    workspace_name: str,
    dataset_version: str,
    status: str,
    attempt_count: int = 0,
) -> tuple[EvaluationRun, Path]:
    workspace = Workspace(name=workspace_name, embedding_profile=None)
    db_session.add(workspace)
    await db_session.flush()
    dataset_path = tmp_path / f"{dataset_version}.json"
    dataset_path.write_text(
        json.dumps({"version": dataset_version, "questions": []}),
        encoding="utf-8",
    )
    run = EvaluationRun(
        workspace_id=workspace.id,
        strategy="semantic",
        status=status,
        dataset_version=dataset_version,
        attempt_count=attempt_count,
    )
    db_session.add(run)
    await db_session.flush()
    await db_session.commit()  # visible to the lifespan's own DB connection below
    return run, workspace.id


@pytest.mark.asyncio
async def test_startup_sweep_drives_interrupted_evaluation_run_to_terminal_state(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # T023: same crash simulation as test_ingestion_restart_recovery.py's
    # `running`-left case, for EvaluationRun.
    run, workspace_id = await _seed_run(
        db_session,
        tmp_path,
        workspace_name="eval-restart-recovery",
        dataset_version="eval-restart-recovery",
        status="running",
    )

    try:
        import decision_assistant.main as main_module

        monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

        app = create_app(
            Settings(
                auth_jwt_secret="test-signing-secret-for-eval-restart-recovery",
                upload_directory=tmp_path,
                evaluation_dataset_path=tmp_path / "eval-restart-recovery.json",
            )
        )
        app.state.provider_bundle_factory = FakeProviderBundleFactory()

        async with _loop_local_evaluation_runner(monkeypatch):
            async with app.router.lifespan_context(app):
                tasks = app.state.startup_redispatch_tasks
                assert len(tasks) == 1
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

        await db_session.refresh(run)
        assert run.status == "completed"
        assert run.attempt_count == 1
        assert run.failure is None
    finally:
        workspace = await db_session.get(Workspace, workspace_id)
        if workspace is not None:
            await db_session.delete(workspace)
            await db_session.commit()


@pytest.mark.asyncio
async def test_startup_sweep_also_recovers_evaluation_run_left_pending_before_dispatch_started(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Same DB27-class gap as ingestion: a run whose fire-and-forget
    # `background_tasks.add_task(runner.dispatch, run.id)` (evaluation/router.py)
    # crashed before it ever flipped the row to `running` would otherwise be
    # invisible to a `statuses=("running",)`-only sweep.
    run, workspace_id = await _seed_run(
        db_session,
        tmp_path,
        workspace_name="eval-restart-recovery-pending",
        dataset_version="eval-restart-recovery-pending",
        status="pending",
    )

    try:
        import decision_assistant.main as main_module

        monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

        app = create_app(
            Settings(
                auth_jwt_secret="test-signing-secret-for-eval-restart-recovery-pending",
                upload_directory=tmp_path,
                evaluation_dataset_path=tmp_path / "eval-restart-recovery-pending.json",
            )
        )
        app.state.provider_bundle_factory = FakeProviderBundleFactory()

        async with _loop_local_evaluation_runner(monkeypatch):
            async with app.router.lifespan_context(app):
                tasks = app.state.startup_redispatch_tasks
                assert len(tasks) == 1
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

        await db_session.refresh(run)
        assert run.status == "completed"
        assert run.attempt_count == 1
    finally:
        workspace = await db_session.get(Workspace, workspace_id)
        if workspace is not None:
            await db_session.delete(workspace)
            await db_session.commit()


@pytest.mark.asyncio
async def test_startup_sweep_marks_run_at_max_attempts_failed_with_reason_and_timestamp(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # DB28: `main.py`'s actual call site must pass `error_field="failure"` and
    # `finished_at_field="completed_at"` — dropping either survives every
    # other test in this file, since those tests only exercise the
    # `requeued` (under-`max_attempts`) path, never the terminal `failed`
    # path through the real lifespan sweep.
    run, workspace_id = await _seed_run(
        db_session,
        tmp_path,
        workspace_name="eval-restart-recovery-max-attempts",
        dataset_version="eval-restart-recovery-max-attempts",
        status="running",
        attempt_count=3,  # == default max_evaluation_attempts
    )

    try:
        import decision_assistant.main as main_module

        monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

        app = create_app(
            Settings(
                auth_jwt_secret="test-signing-secret-for-eval-max-attempts",
                upload_directory=tmp_path,
                evaluation_dataset_path=tmp_path / "eval-restart-recovery-max-attempts.json",
            )
        )
        app.state.provider_bundle_factory = FakeProviderBundleFactory()

        async with app.router.lifespan_context(app):
            # A row at max attempts is marked terminal `failed` directly, no
            # redispatch — nothing to await here.
            assert len(app.state.startup_redispatch_tasks) == 0

        await db_session.refresh(run)
        assert run.status == "failed"
        assert run.attempt_count == 3
        assert run.failure == {"code": "evaluation_interrupted"}
        assert run.completed_at is not None
    finally:
        workspace = await db_session.get(Workspace, workspace_id)
        if workspace is not None:
            await db_session.delete(workspace)
            await db_session.commit()
