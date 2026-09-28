"""Shared dataset, executor and judge fakes for the evaluation-run tests (DB53).

Extracted from `test_evaluation_runs.py` so it and `test_evaluation_runs_api.py` stay under
AGENTS.md's 500-line cap for hand-written files; DB30 and DB49 set the same precedent
(`tests/support/`).
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.evaluation.models import EvaluationQuestion, EvaluationRun
from decision_assistant.providers.base import GenerationRequest

DATASET_VERSION = "decision-eval-v1"
WORKSPACE_ID = UUID("66666666-6666-6666-6666-666666666666")
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


def write_dataset(path: Path, *, version: str = DATASET_VERSION) -> Path:
    dataset = {
        "version": version,
        "questions": [
            {
                "id": "q1",
                "question": "Why was authentication postponed?",
                "expected_answer_summary": "Imports were unstable.",
                "expected_documents": [{"document_id": "doc-1"}],
                "expected_passages": [{"passage_id": "gold-1"}],
                "expected_status": "active",
                "expectation": "answer",
                "facets": {"reason": "answer"},
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
                "facets": {"owner": "answer"},
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
                "facets": {"billing_owner": "abstain"},
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
        self.embedding_profile = EMBEDDING_PROFILE
        self.generation_profile = GENERATION_PROFILE

    async def execute(
        self,
        question: EvaluationQuestion,
        *,
        run_id: UUID,
        strategy: str,
        configuration: dict[str, Any],
        workspace_id: UUID,
    ) -> dict[str, Any]:
        run = await self.session.get(EvaluationRun, run_id)
        assert run is not None
        await self.session.refresh(run)
        self.observed_progress.append(
            (run.status, run.completed_questions, run.total_questions)
        )
        assert strategy in {
            "semantic",
            "hybrid",
            "passage_hybrid",
            "sentence_expanded",
            "parent_child_merged",
        }
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
                "claims": []
                if should_abstain
                else [
                    {
                        "text": "Supported claim",
                        "passage_ids": [expected_passage_ids[0]],
                    }
                ],
                "citations": []
                if should_abstain
                else [{"passage_id": expected_passage_ids[0]}],
            },
            "citation_checks": []
            if should_abstain
            else [
                {
                    "passage_id": expected_passage_ids[0],
                    "document_name": "gold.md",
                    "structurally_valid": True,
                    "matches_gold_evidence": True,
                }
            ],
            "actual_values": {
                "expectation": "abstain" if should_abstain else "answer"
            },
            "latency_ms": 25.0,
        }


class RecordingJudge:
    def __init__(self) -> None:
        self.calls: list[tuple[GenerationRequest, dict[str, Any]]] = []
        self.profile = JUDGE_PROFILE

    async def judge(
        self,
        request: GenerationRequest,
        *,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((request, profile))
        return {
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
