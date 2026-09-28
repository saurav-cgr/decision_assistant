"""Evaluation runs over HTTP: creation, snapshots and post-run corpus isolation (DB53).

Split out of `test_evaluation_runs.py`; the shared dataset, executor and judge fakes live in
`tests/support/evaluation_run_fixtures.py`.
"""

from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.evaluation.models import EvaluationResult
from decision_assistant.ingestion.models import Document, DocumentVersion
from decision_assistant.main import create_app
from decision_assistant.workspace.context import WorkspaceContext
from decision_assistant.workspace.models import Workspace
from tests.support.evaluation_run_fixtures import (
    DATASET_VERSION,
    EMBEDDING_PROFILE,
    GENERATION_PROFILE,
    JUDGE_PROFILE,
    RUN_CONFIGURATION,
    WORKSPACE_ID,
    RecordingExecutor,
    RecordingJudge,
    run_request,
    write_dataset,
)

@pytest.mark.asyncio
async def test_semantic_and_hybrid_runs_keep_identical_snapshots(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service_module = import_module("decision_assistant.evaluation.service")
    schemas = import_module("decision_assistant.evaluation.schemas")
    service = service_module.EvaluationService(
        session=db_session,
        dataset_path=write_dataset(tmp_path / "questions.json"),
        executor=RecordingExecutor(db_session),
        judge=RecordingJudge(),
    )
    spoofed = {
        "generation_profile": {"provider": "client-spoof"},
        "embedding_profile": {"provider": "client-spoof"},
        "judge_profile": {"provider": "client-spoof"},
    }
    semantic = await service.create_run(
        run_request(schemas, "semantic").model_copy(update=spoofed)
    )
    hybrid = await service.create_run(
        run_request(schemas, "hybrid").model_copy(update=spoofed)
    )

    await service.execute_run(semantic.id)
    await service.execute_run(hybrid.id)
    await db_session.refresh(semantic)
    await db_session.refresh(hybrid)

    assert semantic.dataset_version == hybrid.dataset_version == DATASET_VERSION
    assert semantic.configuration == hybrid.configuration == RUN_CONFIGURATION
    assert semantic.generation_profile == hybrid.generation_profile == GENERATION_PROFILE
    assert semantic.embedding_profile == hybrid.embedding_profile == EMBEDDING_PROFILE
    assert semantic.judge_profile == hybrid.judge_profile == JUDGE_PROFILE

    async def expected_snapshots(run_id: UUID) -> list[dict[str, Any]]:
        return list(
            await db_session.scalars(
                select(EvaluationResult.expected_values)
                .where(EvaluationResult.evaluation_run_id == run_id)
                .order_by(EvaluationResult.evaluation_question_id)
            )
        )

    assert await expected_snapshots(semantic.id) == await expected_snapshots(
        hybrid.id
    )


@pytest.mark.asyncio
async def test_evaluation_api_starts_run_and_returns_completed_detail(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service_module = import_module("decision_assistant.evaluation.service")
    router_module = import_module("decision_assistant.evaluation.router")
    service = service_module.EvaluationService(
        session=db_session,
        dataset_path=write_dataset(tmp_path / "questions.json"),
        executor=RecordingExecutor(db_session),
        judge=RecordingJudge(),
    )
    db_session.add(
        Workspace(
            id=WORKSPACE_ID,
            name=f"Evaluation workspace {WORKSPACE_ID}",
            embedding_profile=None,
        )
    )
    await db_session.flush()
    app = create_app()
    app.dependency_overrides[router_module.get_evaluation_service] = lambda: service
    app.dependency_overrides[router_module.get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )

    class TestRunner:
        async def dispatch(self, run_id: UUID) -> None:
            await service.execute_run(run_id)

    app.dependency_overrides[
        router_module.get_evaluation_background_runner
    ] = TestRunner

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        started = await client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/evaluations/runs",
            json={
                "strategy": "hybrid",
                "dataset_version": DATASET_VERSION,
                "configuration": RUN_CONFIGURATION,
                "generation_profile": GENERATION_PROFILE,
                "embedding_profile": EMBEDDING_PROFILE,
                "judge_profile": JUDGE_PROFILE,
            },
        )

        assert started.status_code == 202
        run_id = started.json()["id"]
        detail = await client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/evaluations/runs/{run_id}"
        )

    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["completed_questions"] == 3
    assert detail.json()["total_questions"] == 3
    assert len(detail.json()["results"]) == 3


@pytest.mark.asyncio
async def test_run_snapshots_active_corpus_and_ignores_later_changes(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE

    workspace = Workspace(name="Snapshot workspace", embedding_profile=None)
    db_session.add(workspace)
    await db_session.flush()
    document = Document(
        workspace_id=workspace.id,
        display_name="snap.md",
        media_type="text/markdown",
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        checksum="a" * 64,
        storage_path="snap.md",
        normalized_content="Auth decision.",
        chunking_profile=CURRENT_CHUNKING_PROFILE,
        state="active",
    )
    db_session.add(version)
    await db_session.flush()
    document.active_version_id = version.id

    dataset_path = tmp_path / "snap-questions.json"
    write_dataset(dataset_path, version="snap-v1")
    service_module = import_module("decision_assistant.evaluation.service")
    schemas = import_module("decision_assistant.evaluation.schemas")
    service = service_module.EvaluationService(
        session=db_session,
        dataset_path=dataset_path,
        executor=RecordingExecutor(db_session),
        judge=RecordingJudge(),
    )

    run_one = await service.create_run(
        schemas.EvaluationRunRequest(
            strategy="hybrid",
            dataset_version="snap-v1",
            judge_profile={"temperature": 0},
        ),
        workspace_id=workspace.id,
    )
    assert run_one.corpus_snapshot == [
        {
            "document_version_id": str(version.id),
            "chunking_profile": CURRENT_CHUNKING_PROFILE,
            "source_kind": "markdown",
        }
    ]

    # Retire the active version; a later run must snapshot the empty corpus.
    version.state = "retired"
    document.active_version_id = None
    await db_session.flush()
    run_two = await service.create_run(
        schemas.EvaluationRunRequest(
            strategy="hybrid",
            dataset_version="snap-v1",
            judge_profile={"temperature": 0},
        ),
        workspace_id=workspace.id,
    )
    assert run_two.corpus_snapshot == []
