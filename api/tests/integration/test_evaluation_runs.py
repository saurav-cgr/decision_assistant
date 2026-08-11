import json
from collections.abc import AsyncIterator
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.main import create_app
from decision_assistant.models import (
    Document,
    DocumentVersion,
    EvaluationQuestion,
    EvaluationResult,
    EvaluationRun,
    Passage,
    Workspace,
)


DATASET_VERSION = "decision-eval-v1"
RUN_CONFIGURATION = {
    "top_k": 5,
    "answer_prompt_version": "answer-v1",
}
GENERATION_PROFILE = {"provider": "fake", "model": "answer-model"}
EMBEDDING_PROFILE = {
    "provider": "fake",
    "model": "embedding-model",
    "dimension": 768,
}
JUDGE_PROFILE = {
    "provider": "fake",
    "model": "judge-model",
    "temperature": 0.0,
}


def write_dataset(path: Path) -> Path:
    dataset = {
        "version": DATASET_VERSION,
        "questions": [
            {
                "id": "q1",
                "question": "Why was authentication postponed?",
                "expected_answer_summary": "Imports were unstable.",
                "expected_documents": [{"document_id": "doc-1"}],
                "expected_passages": [{"passage_id": "gold-1"}],
                "expected_status": "active",
                "expectation": "answer",
                "tags": ["authentication"],
            },
            {
                "id": "q2",
                "question": "Who owns authentication?",
                "expected_answer_summary": "Maya owns authentication.",
                "expected_documents": [{"document_id": "doc-1"}],
                "expected_passages": [{"passage_id": "gold-2"}],
                "expected_status": "active",
                "expectation": "answer",
                "tags": ["owner"],
            },
            {
                "id": "q3",
                "question": "Who owns the unsupported billing migration?",
                "expected_answer_summary": None,
                "expected_documents": [],
                "expected_passages": [],
                "expected_status": None,
                "expectation": "abstain",
                "tags": ["abstention"],
            },
        ],
    }
    path.write_text(json.dumps(dataset), encoding="utf-8")
    return path


def run_request(schemas: Any, strategy: str) -> Any:
    return schemas.EvaluationRunRequest(
        strategy=strategy,
        dataset_version=DATASET_VERSION,
        configuration=RUN_CONFIGURATION,
        generation_profile=GENERATION_PROFILE,
        embedding_profile=EMBEDDING_PROFILE,
        judge_profile=JUDGE_PROFILE,
    )


class RecordingExecutor:
    def __init__(
        self,
        session: AsyncSession,
        *,
        isolated_failure_id: str | None = None,
        fatal_error: Exception | None = None,
    ) -> None:
        self.session = session
        self.isolated_failure_id = isolated_failure_id
        self.fatal_error = fatal_error
        self.observed_progress: list[tuple[str, int, int]] = []

    async def execute(
        self,
        question: EvaluationQuestion,
        *,
        run_id: UUID,
        strategy: str,
        configuration: dict[str, Any],
    ) -> dict[str, Any]:
        run = await self.session.get(EvaluationRun, run_id)
        assert run is not None
        await self.session.refresh(run)
        self.observed_progress.append(
            (run.status, run.completed_questions, run.total_questions)
        )
        assert strategy in {"semantic", "hybrid"}
        assert configuration == RUN_CONFIGURATION
        if self.fatal_error is not None:
            raise self.fatal_error
        if question.external_id == self.isolated_failure_id:
            raise RuntimeError("question execution failed")

        should_abstain = question.expectation == "abstain"
        expected_passage_ids = [
            item["passage_id"] for item in question.expected_passages
        ]
        return {
            "retrieved_ids": expected_passage_ids or ["unrelated"],
            "generated_output": {
                "state": "abstained" if should_abstain else "answered",
                "answer": (
                    "Insufficient evidence."
                    if should_abstain
                    else question.expected_answer_summary
                ),
                "claims": [] if should_abstain else [{"text": "Supported claim"}],
                "citations": []
                if should_abstain
                else [{"passage_id": expected_passage_ids[0]}],
            },
            "citation_checks": []
            if should_abstain
            else [{"structurally_valid": True, "gold_relevant": True}],
            "actual_values": {
                "expectation": "abstain" if should_abstain else "answer"
            },
            "latency_ms": 25.0,
        }


class RecordingJudge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def judge(
        self,
        prompt: str,
        *,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((prompt, profile))
        return {
            "claims": [{"claim_index": 0, "supported": True}],
            "supported_claims": 1,
            "total_claims": 1,
        }


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
    assert "claim-support-v1" in judged.judge_prompt
    assert "Why was authentication postponed?" in judged.judge_prompt
    assert judged.judge_profile == JUDGE_PROFILE
    assert judged.judge_output == {
        "claims": [{"claim_index": 0, "supported": True}],
        "supported_claims": 1,
        "total_claims": 1,
    }
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
    semantic = await service.create_run(run_request(schemas, "semantic"))
    hybrid = await service.create_run(run_request(schemas, "hybrid"))

    await service.execute_run(semantic.id)
    await service.execute_run(hybrid.id)
    await db_session.refresh(semantic)
    await db_session.refresh(hybrid)

    assert semantic.dataset_version == hybrid.dataset_version == DATASET_VERSION
    assert semantic.configuration == hybrid.configuration == RUN_CONFIGURATION
    assert semantic.generation_profile == hybrid.generation_profile
    assert semantic.embedding_profile == hybrid.embedding_profile
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
    app = create_app()
    app.dependency_overrides[router_module.get_evaluation_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        started = await client.post(
            "/api/v1/evaluations/runs",
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
        detail = await client.get(f"/api/v1/evaluations/runs/{run_id}")

    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["completed_questions"] == 3
    assert detail.json()["total_questions"] == 3
    assert len(detail.json()["results"]) == 3
