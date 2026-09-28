from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.evaluation.models import EvaluationRun
from decision_assistant.ingestion.models import Document, DocumentVersion, IngestionJob
from decision_assistant.jobs.recovery import recover_and_requeue
from decision_assistant.workspace.models import Workspace


async def _make_job(
    session: AsyncSession,
    *,
    attempt_count: int,
    request_id: str,
) -> IngestionJob:
    workspace = Workspace(name=f"recovery-{request_id}", embedding_profile=None)
    session.add(workspace)
    await session.flush()
    document = Document(
        workspace_id=workspace.id,
        display_name="interrupted.md",
        media_type="text/markdown",
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        checksum="a" * 64,
        storage_path="interrupted.md",
        state="staging",
    )
    session.add(version)
    await session.flush()
    job = IngestionJob(
        document_id=document.id,
        document_version_id=version.id,
        stage="parsing",
        status="running",
        progress=10,
        attempt_count=attempt_count,
        request_id=request_id,
    )
    session.add(job)
    await session.flush()
    return job


@pytest.mark.asyncio
async def test_running_job_under_max_attempts_is_requeued(
    db_session: AsyncSession,
) -> None:
    job = await _make_job(db_session, attempt_count=0, request_id="requeue-me")

    outcome = await recover_and_requeue(
        db_session,
        model=IngestionJob,
        max_attempts=3,
        interrupted_error_code="ingestion_interrupted",
    )

    assert job.status == "pending"
    assert job.attempt_count == 1
    assert job.id in [row.id for row in outcome.requeued]
    assert outcome.failed == []


@pytest.mark.asyncio
async def test_running_job_at_max_attempts_is_marked_failed(
    db_session: AsyncSession,
) -> None:
    job = await _make_job(db_session, attempt_count=3, request_id="give-up")

    outcome = await recover_and_requeue(
        db_session,
        model=IngestionJob,
        max_attempts=3,
        interrupted_error_code="ingestion_interrupted",
    )

    assert job.status == "failed"
    assert job.error == {"code": "ingestion_interrupted"}
    assert job.id in [row.id for row in outcome.failed]
    assert outcome.requeued == []


@pytest.mark.asyncio
async def test_pending_and_completed_jobs_are_untouched(
    db_session: AsyncSession,
) -> None:
    pending_job = await _make_job(db_session, attempt_count=0, request_id="already-pending")
    pending_job.status = "pending"
    completed_job = await _make_job(db_session, attempt_count=0, request_id="already-done")
    completed_job.status = "completed"
    await db_session.flush()

    outcome = await recover_and_requeue(
        db_session,
        model=IngestionJob,
        max_attempts=3,
        interrupted_error_code="ingestion_interrupted",
    )

    assert pending_job.status == "pending"
    assert completed_job.status == "completed"
    touched_ids: set[UUID] = {row.id for row in outcome.requeued} | {
        row.id for row in outcome.failed
    }
    assert pending_job.id not in touched_ids
    assert completed_job.id not in touched_ids


@pytest.mark.asyncio
async def test_error_field_targets_evaluation_run_failure_column(
    db_session: AsyncSession,
) -> None:
    # T023: EvaluationRun names its failure column `failure`, not `error` —
    # `recover_and_requeue`'s `error_field` must actually persist to that
    # column, not silently set an unmapped Python attribute.
    workspace = Workspace(name="eval-recovery-error-field", embedding_profile=None)
    db_session.add(workspace)
    await db_session.flush()
    run = EvaluationRun(
        workspace_id=workspace.id,
        strategy="semantic",
        status="running",
        dataset_version="v1",
        attempt_count=3,
    )
    db_session.add(run)
    await db_session.flush()

    outcome = await recover_and_requeue(
        db_session,
        model=EvaluationRun,
        max_attempts=3,
        interrupted_error_code="evaluation_interrupted",
        error_field="failure",
    )

    assert run.status == "failed"
    assert run.failure == {"code": "evaluation_interrupted"}
    assert run.id in [row.id for row in outcome.failed]
    assert not hasattr(run, "error")


@pytest.mark.asyncio
async def test_finished_at_field_stamps_terminal_timestamp_when_given(
    db_session: AsyncSession,
) -> None:
    # DB28: a row recovery marks terminal `failed` should get its terminal
    # timestamp stamped too, matching a normal failure elsewhere
    # (`_record_dispatch_failure`'s `finished_at`, `_fail_run`'s `completed_at`).
    job = await _make_job(db_session, attempt_count=3, request_id="finished-at-check")
    assert job.finished_at is None

    await recover_and_requeue(
        db_session,
        model=IngestionJob,
        max_attempts=3,
        interrupted_error_code="ingestion_interrupted",
        finished_at_field="finished_at",
    )

    assert job.status == "failed"
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_finished_at_field_defaults_to_no_stamp(
    db_session: AsyncSession,
) -> None:
    # Default `finished_at_field=None` must not touch any timestamp column —
    # existing callers that never pass it keep their prior behavior exactly.
    job = await _make_job(db_session, attempt_count=3, request_id="no-stamp-check")

    await recover_and_requeue(
        db_session,
        model=IngestionJob,
        max_attempts=3,
        interrupted_error_code="ingestion_interrupted",
    )

    assert job.status == "failed"
    assert job.finished_at is None
