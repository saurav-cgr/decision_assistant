from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.models import (
    EvaluationQuestion,
    EvaluationResult,
    EvaluationRun,
    Workspace,
)


@pytest.mark.asyncio
async def test_evaluation_answer_diagnostics_round_trip(
    db_session: AsyncSession,
) -> None:
    nullable = await db_session.scalar(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'evaluation_results' "
            "AND column_name = 'answer_diagnostics'"
        )
    )
    assert nullable == "YES"

    workspace = Workspace(name=f"Diagnostics {uuid4()}")
    db_session.add(workspace)
    await db_session.flush()
    question = EvaluationQuestion(
        workspace_id=workspace.id,
        external_id="diagnostic-1",
        dataset_version="diagnostic-v1",
        question="Why was authentication postponed?",
        expected_answer_summary="Audit events were incomplete.",
        expected_documents=[],
        expected_passages=[],
        expected_status="active",
        expectation="answer",
        tags=[],
    )
    run = EvaluationRun(
        workspace_id=workspace.id,
        strategy="hybrid",
        status="pending",
        completed_questions=0,
        total_questions=1,
        failure=None,
        configuration={},
        dataset_version="diagnostic-v1",
        generation_profile={},
        embedding_profile={},
        judge_profile={},
        corpus_snapshot=[],
        aggregate_metrics=None,
    )
    db_session.add_all([question, run])
    await db_session.flush()
    diagnostics = {
        "outcome_reason": "verification_failed",
        "generation_attempt_count": 2,
        "repair_attempted": True,
        "verifier_errors": [{"code": "central_claim_uncited"}],
    }
    result = EvaluationResult(
        evaluation_run_id=run.id,
        evaluation_question_id=question.id,
        retrieved_ranks={"ids": [], "ranks": {}},
        generated_output=None,
        answer_diagnostics=diagnostics,
        citation_checks={"checks": []},
        expected_values={},
        actual_values={"expectation": "abstain"},
    )
    db_session.add(result)
    await db_session.flush()

    stored = await db_session.scalar(
        select(EvaluationResult.answer_diagnostics).where(
            EvaluationResult.id == result.id
        )
    )
    assert stored == diagnostics
