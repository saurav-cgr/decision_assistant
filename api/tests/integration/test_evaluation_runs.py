"""Evaluation runs: the background runner, progress, failures and corpus snapshots.

The HTTP-level runs live in `test_evaluation_runs_api.py`, and the shared dataset/executor/judge
fakes in `tests/support/evaluation_run_fixtures.py` (DB53: AGENTS.md's 500-line cap).
"""

import json
from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from decision_assistant.config import Settings, get_settings
from decision_assistant.evaluation.models import (
    EvaluationQuestion,
    EvaluationResult,
    EvaluationRun,
)
from decision_assistant.ingestion.models import Document, DocumentVersion, Passage
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.workspace.models import Workspace
from tests.support.evaluation_run_fixtures import (
    JUDGE_PROFILE,
    RUN_CONFIGURATION,
    RecordingExecutor,
    RecordingJudge,
    run_request,
    write_dataset,
)


@pytest.mark.asyncio
async def test_background_runner_persists_after_request_session_teardown(
    tmp_path: Path,
) -> None:
    router_module = import_module("decision_assistant.evaluation.router")
    schemas = import_module("decision_assistant.evaluation.schemas")
    dataset_version = f"background-{uuid4()}"
    settings = Settings(
        database_url=get_settings().database_url,
        evaluation_dataset_path=write_dataset(
            tmp_path / "background.json",
            version=dataset_version,
        ),
    )
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    bundle = ProviderBundle(
        embedding=FakeEmbeddingProvider(dimension=768),
        generation=FakeGenerationProvider(),
    )
    run_id: UUID | None = None
    question_ids: list[UUID] = []
    try:
        async with maker() as request_session:
            service = router_module._build_evaluation_service(
                request_session,
                settings,
                bundle,
            )
            request = schemas.EvaluationRunRequest(
                strategy="semantic",
                dataset_version=dataset_version,
                configuration=RUN_CONFIGURATION,
            )
            run = await service.create_run(request)
            run_id = run.id
            question_ids = list(
                await request_session.scalars(
                    select(EvaluationQuestion.id).where(
                        EvaluationQuestion.dataset_version == dataset_version
                    )
                )
            )
            await request_session.commit()

        runner = router_module.EvaluationBackgroundRunner(
            settings,
            lambda: bundle,
            session_maker=maker,
        )
        await runner.dispatch(run_id)

        async with maker() as verification_session:
            persisted = await verification_session.get(EvaluationRun, run_id)
            assert persisted is not None
            assert persisted.status == "completed"
    finally:
        async with maker() as cleanup_session:
            if run_id is not None:
                await cleanup_session.execute(
                    delete(EvaluationResult).where(
                        EvaluationResult.evaluation_run_id == run_id
                    )
                )
                await cleanup_session.execute(
                    delete(RetrievalTrace).where(
                        RetrievalTrace.request_id.like(f"evaluation:{run_id}:%")
                    )
                )
                await cleanup_session.execute(
                    delete(EvaluationRun).where(EvaluationRun.id == run_id)
                )
            if question_ids:
                await cleanup_session.execute(
                    delete(EvaluationQuestion).where(
                        EvaluationQuestion.id.in_(question_ids)
                    )
                )
            await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_run_resolves_stable_gold_source_references(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    workspace = Workspace(name="Atlas", embedding_profile=None)
    db_session.add(workspace)
    await db_session.flush()
    document = Document(
        workspace_id=workspace.id,
        display_name="meeting.md",
        media_type="text/markdown",
        active_version_id=None,
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        title="Meeting",
        document_date=None,
        participants=[],
        source_type="meeting_notes",
        project="Atlas",
        checksum="a" * 64,
        storage_path="atlas/meeting.md",
        normalized_content="Authentication remains postponed.",
        state="active",
        error=None,
    )
    db_session.add(version)
    await db_session.flush()
    document.active_version_id = version.id
    passage = Passage(
        document_version_id=version.id,
        sequence_number=0,
        content="Decision: Authentication remains postponed to Q4.",
        start_offset=0,
        end_offset=52,
        content_hash="b" * 64,
        locator={"kind": "lines", "start": 11, "end": 15},
        embedding=[0.0] * 768,
    )
    db_session.add(passage)
    await db_session.flush()

    dataset_path = tmp_path / "stable-questions.json"
    dataset_path.write_text(
        json.dumps(
            {
                "version": "stable-v1",
                "questions": [
                    {
                        "id": "stable-1",
                        "question": "What happened to authentication?",
                        "expected_claims": [
                            {"text": "Authentication remains postponed to Q4."}
                        ],
                        "expected_documents": [{"document": "meeting.md"}],
                        "expected_passages": [
                            {
                                "document": "meeting.md",
                                "quote": "Authentication remains postponed to Q4.",
                                "locator": {
                                    "kind": "lines",
                                    "start": 13,
                                    "end": 13,
                                },
                            }
                        ],
                        "expected_status": "active",
                        "expectation": "answer",
                        "facets": {"decision": "answer"},
                        "tags": ["authentication"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service_module = import_module("decision_assistant.evaluation.service")
    schemas = import_module("decision_assistant.evaluation.schemas")
    service = service_module.EvaluationService(
        session=db_session,
        dataset_path=dataset_path,
        executor=RecordingExecutor(db_session),
        judge=RecordingJudge(),
    )

    await service.create_run(
        schemas.EvaluationRunRequest(
            strategy="hybrid",
            dataset_version="stable-v1",
            judge_profile={"temperature": 0},
        )
    )

    stored = await db_session.scalar(
        select(EvaluationQuestion).where(
            EvaluationQuestion.external_id == "stable-1"
        )
    )
    assert stored is not None
    assert stored.expected_documents == [
        {"document": "meeting.md", "document_id": str(document.id)}
    ]
    assert stored.expected_passages == [
        {
            "document": "meeting.md",
            "quote": "Authentication remains postponed to Q4.",
            "locator": {"kind": "lines", "start": 13, "end": 13},
            "document_id": str(document.id),
            "passage_id": str(passage.id),
        }
    ]


@pytest.mark.asyncio
async def test_run_completes_with_progress_isolated_failures_and_judge_audit(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service_module = import_module("decision_assistant.evaluation.service")
    schemas = import_module("decision_assistant.evaluation.schemas")
    dataset_path = write_dataset(tmp_path / "questions.json")
    executor = RecordingExecutor(db_session, isolated_failure_id="q2")
    judge = RecordingJudge()
    service = service_module.EvaluationService(
        session=db_session,
        dataset_path=dataset_path,
        executor=executor,
        judge=judge,
    )

    run = await service.create_run(run_request(schemas, "hybrid"))

    assert run.status == "pending"
    assert run.completed_questions == 0
    assert run.total_questions == 3

    await service.execute_run(run.id)
    await db_session.refresh(run)

    assert executor.observed_progress == [
        ("running", 0, 3),
        ("running", 1, 3),
        ("running", 2, 3),
    ]
    assert run.status == "completed"
    assert run.completed_questions == 3
    assert run.total_questions == 3
    assert run.failure is None
    assert run.aggregate_metrics is not None

    rows = (
        await db_session.execute(
            select(EvaluationResult, EvaluationQuestion)
            .join(
                EvaluationQuestion,
                EvaluationQuestion.id == EvaluationResult.evaluation_question_id,
            )
            .where(EvaluationResult.evaluation_run_id == run.id)
            .order_by(EvaluationQuestion.external_id)
        )
    ).all()
    assert len(rows) == 3
    result_by_id = {question.external_id: result for result, question in rows}
    assert result_by_id["q2"].failure_reason == "question execution failed"
    assert result_by_id["q1"].failure_reason is None
    assert result_by_id["q3"].failure_reason is None

    judged = result_by_id["q1"]
    assert judged.judge_prompt is not None
    assert "claim-support-v3" in judged.judge_prompt
    assert "Why was authentication postponed?" in judged.judge_prompt
    assert judged.judge_profile == JUDGE_PROFILE
    assert judged.judge_output == {
        "claims": [{"claim_index": 0, "supported": True}],
        "citation_assessments": [
            {
                "claim_index": 0,
                "passage_id": "gold-1",
                "supported": True,
                "reason": "The passage supports the claim.",
            }
        ],
        "facet_outcomes": {"reason": "answer"},
        "supported_claims": 1,
        "total_claims": 1,
    }
    assert judged.actual_values == {
        "expectation": "answer",
        "facets": {"reason": "answer"},
    }
    assert judged.citation_checks == {
        "checks": [
            {
                "claim_index": 0,
                "claim": "Supported claim",
                "passage_id": "gold-1",
                "document_name": "gold.md",
                "structurally_valid": True,
                "matches_gold_evidence": True,
                "supports_claim": True,
                "reason": "The passage supports the claim.",
            }
        ]
    }
    assert run.aggregate_metrics["gold_citation_coverage"] == 0.5
    assert run.aggregate_metrics["facet_abstention_accuracy"] == pytest.approx(2 / 3)
    assert judge.calls[0][1] == JUDGE_PROFILE


@pytest.mark.asyncio
async def test_fatal_error_marks_run_failed_with_structured_error(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service_module = import_module("decision_assistant.evaluation.service")
    schemas = import_module("decision_assistant.evaluation.schemas")
    fatal_error = service_module.FatalEvaluationError(
        code="provider_unavailable",
        message="Judge unavailable",
    )
    service = service_module.EvaluationService(
        session=db_session,
        dataset_path=write_dataset(tmp_path / "questions.json"),
        executor=RecordingExecutor(db_session, fatal_error=fatal_error),
        judge=RecordingJudge(),
    )
    run = await service.create_run(run_request(schemas, "semantic"))

    await service.execute_run(run.id)
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.completed_questions == 0
    assert run.failure == {
        "code": "provider_unavailable",
        "message": "Judge unavailable",
    }
    assert run.completed_at is not None

